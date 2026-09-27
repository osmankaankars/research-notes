// Package fixtureapi is a local, artificial credential-scoped fixture service.
// It is not a cloud emulator and its tests are not evidence of OCI isolation.
package fixtureapi

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"
)

var ErrNotFound = errors.New("fixture object not found")

type Object struct {
	ID       string `json:"id"`
	Upstream string `json:"upstream"`
}
type store struct {
	mu      sync.Mutex
	scope   string
	token   []byte
	objects map[string]Object
}

var scopeRE = regexp.MustCompile(`^[a-z][a-z0-9_-]{0,31}$`)

func NewHandler(scope string, token []byte) http.Handler {
	s := &store{scope: scope, token: append([]byte(nil), token...), objects: map[string]Object{}}
	return http.HandlerFunc(s.serve)
}
func (s *store) serve(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	if !scopeRE.MatchString(s.scope) || len(s.token) < 8 {
		http.Error(w, "invalid fixture setup", 500)
		return
	}
	got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if subtle.ConstantTimeCompare([]byte(got), s.token) != 1 {
		http.Error(w, "unauthorized", 401)
		return
	}
	if r.URL.Path == "/objects" && r.Method == "POST" {
		var body struct {
			Upstream string `json:"upstream"`
		}
		d := json.NewDecoder(io.LimitReader(r.Body, 4097))
		d.DisallowUnknownFields()
		if d.Decode(&body) != nil || len(body.Upstream) > 2048 {
			http.Error(w, "invalid request", 400)
			return
		}
		var extra any
		if d.Decode(&extra) != io.EOF {
			http.Error(w, "trailing request", 400)
			return
		}
		var b [16]byte
		if _, err := rand.Read(b[:]); err != nil {
			http.Error(w, "rng failed", 500)
			return
		}
		o := Object{ID: s.scope + "-" + hex.EncodeToString(b[:]), Upstream: body.Upstream}
		s.mu.Lock()
		s.objects[o.ID] = o
		s.mu.Unlock()
		w.WriteHeader(201)
		json.NewEncoder(w).Encode(o)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/objects/")
	if id == r.URL.Path || strings.Contains(id, "/") {
		http.NotFound(w, r)
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	o, ok := s.objects[id]
	if !ok {
		http.NotFound(w, r)
		return
	}
	switch r.Method {
	case "GET":
		json.NewEncoder(w).Encode(o)
	case "DELETE":
		delete(s.objects, id)
		w.WriteHeader(204)
	default:
		w.WriteHeader(405)
	}
}

type Client struct {
	http  *http.Client
	token string
}

func NewClient(socket string, token []byte) *Client {
	tr := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", socket)
	}, DisableKeepAlives: true}
	return &Client{http: &http.Client{Transport: tr, Timeout: 3 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return errors.New("fixture redirects forbidden") }}, token: string(token)}
}
func (c *Client) do(ctx context.Context, method, path string, body any) (Object, error) {
	var o Object
	raw, err := json.Marshal(body)
	if err != nil {
		return o, err
	}
	r, err := http.NewRequestWithContext(ctx, method, "http://fixture"+path, bytes.NewReader(raw))
	if err != nil {
		return o, err
	}
	r.Header.Set("Authorization", "Bearer "+c.token)
	res, err := c.http.Do(r)
	if err != nil {
		return o, errors.New("fixture transport failed")
	}
	defer res.Body.Close()
	switch res.StatusCode {
	case 404:
		return o, ErrNotFound
	case 204:
		return o, nil
	case 200, 201:
		if json.NewDecoder(io.LimitReader(res.Body, 4096)).Decode(&o) != nil {
			return o, errors.New("invalid fixture response")
		}
		return o, nil
	default:
		return o, errors.New("fixture refused request")
	}
}
func (c *Client) Create(ctx context.Context, upstream string) (Object, error) {
	return c.do(ctx, "POST", "/objects", map[string]string{"upstream": upstream})
}
func (c *Client) Read(ctx context.Context, id string) (Object, error) {
	return c.do(ctx, "GET", "/objects/"+url.PathEscape(id), nil)
}
func (c *Client) Delete(ctx context.Context, id string) error {
	_, err := c.do(ctx, "DELETE", "/objects/"+url.PathEscape(id), nil)
	return err
}
