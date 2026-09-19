"""Loopback-only HTTP confirmation transport using separate supplier processes.

Faults are configured out of band in fixture databases. No controller-facing
fault, clock-advance or database endpoint is exposed. No paid services are used.
"""
from __future__ import annotations
from dataclasses import asdict
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import multiprocessing as mp
from pathlib import Path
import socket
from urllib import error, parse, request
from .contracts import Capability, Operation, Receipt, OutcomeUnknown
from .supplier import Supplier, SupplierEndpoint

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are disabled in the loopback test client')

class HttpSupplierClient:
    def __init__(self,base_url: str,capability: Capability,retention_ticks: int | None):
        url=parse.urlparse(base_url)
        if (url.scheme!='http' or url.hostname!='127.0.0.1' or url.username or url.password
            or url.path not in ('','/') or url.query or url.fragment or not url.port):
            raise ValueError('Only explicit loopback HTTP URLs without credentials are allowed')
        self.base_url=base_url.rstrip('/')
        self.capability=Capability(capability);self.retention_ticks=retention_ticks
        self.opener=request.build_opener(request.ProxyHandler({}),NoRedirect())

    def _request(self,path: str,payload: dict | None=None) -> Receipt:
        data=None if payload is None else json.dumps(payload).encode()
        req=request.Request(self.base_url+path,data=data,headers={'Content-Type':'application/json'})
        try:
            with self.opener.open(req,timeout=5) as response:
                return Receipt.from_dict(json.loads(response.read(65536)))
        except error.HTTPError as exc:
            raise ValueError(f'Provider validation error: HTTP {exc.code}') from exc
        except (error.URLError,OSError,http.client.HTTPException) as exc:
            raise OutcomeUnknown('response unavailable') from exc

    def create(self,op: Operation,attempt_id: str,tick: int) -> Receipt:
        return self._request('/operations',{'operation':asdict(op),'attempt_id':attempt_id,'tick':tick})

    def lookup(self,operation_id: str,tick: int) -> Receipt:
        return self._request(f'/operations/{parse.quote(operation_id,safe="")}?tick={tick}')

    def request_cancel(self,operation_id: str,cancellation_id: str,tick: int) -> Receipt:
        return self._request(f'/operations/{parse.quote(operation_id,safe="")}/cancel',
                             {'cancellation_id':cancellation_id,'tick':tick})


def _serve(path,capability,retention,provider,ready,stop):
    endpoint=SupplierEndpoint(Supplier(Path(path),Capability(capability),retention,provider=provider))
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.0'
        def log_message(self,*args):
            pass
        def reply(self,status,data):
            raw=json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def lost_response(self):
            self.close_connection=True
            try: self.connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            self.connection.close()
        def do_GET(self):
            url=parse.urlparse(self.path)
            try:
                if url.path=='/health':
                    self.reply(200,{'ready':True});return
                bits=parse.unquote(url.path).strip('/').split('/')
                if len(bits)!=2 or bits[0]!='operations':
                    self.reply(404,{'error':'unknown route'});return
                tick=int(parse.parse_qs(url.query)['tick'][0])
                self.reply(200,asdict(endpoint.lookup(bits[1],tick)))
            except (ValueError,KeyError,TypeError): self.reply(400,{'error':'invalid request'})
        def do_POST(self):
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>65536:
                    self.reply(400,{'error':'invalid length'});return
                payload=json.loads(self.rfile.read(length))
                bits=parse.unquote(parse.urlparse(self.path).path).strip('/').split('/')
                if bits==['operations']:
                    result=endpoint.create(Operation(**payload['operation']),payload['attempt_id'],int(payload['tick']))
                elif len(bits)==3 and bits[0]=='operations' and bits[2]=='cancel':
                    result=endpoint.request_cancel(bits[1],payload['cancellation_id'],int(payload['tick']))
                else:
                    self.reply(404,{'error':'unknown route'});return
                self.reply(200,asdict(result))
            except OutcomeUnknown:
                # The operation may already be durable. Close without any HTTP response.
                self.lost_response()
            except (ValueError,KeyError,TypeError): self.reply(400,{'error':'invalid request'})
    server=HTTPServer(('127.0.0.1',0),Handler)
    server.timeout=0.05
    ready.send(server.server_address[1]);ready.close()
    try:
        while not stop.is_set(): server.handle_request()
    finally: server.server_close()


class HttpSupplierProcess:
    def __init__(self,path: Path,capability: Capability,retention_ticks: int | None,provider: str):
        self.path=Path(path);self.capability=Capability(capability)
        self.retention_ticks=retention_ticks;self.provider=provider
        self.process=None;self.client=None

    def start(self):
        if self.process and self.process.is_alive(): raise RuntimeError('Supplier already running')
        ctx=mp.get_context('spawn')
        receiver,sender=ctx.Pipe(duplex=False)
        self.stop_event=ctx.Event()
        self.process=ctx.Process(target=_serve,args=(str(self.path),self.capability.value,
                                  self.retention_ticks,self.provider,sender,self.stop_event))
        self.process.start();sender.close()
        try:
            if not receiver.poll(10): raise TimeoutError('Supplier did not signal readiness')
            port=receiver.recv()
        except Exception:
            self.stop();raise
        finally: receiver.close()
        self.client=HttpSupplierClient(f'http://127.0.0.1:{port}',self.capability,self.retention_ticks)
        return self.client

    def stop(self):
        if not self.process: return
        self.stop_event.set();self.process.join(3)
        if self.process.is_alive():
            self.process.terminate();self.process.join(3)
        self.process.close();self.process=None
