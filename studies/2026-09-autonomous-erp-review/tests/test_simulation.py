import unittest
import numpy as np
import simulation as s

class CoreTests(unittest.TestCase):
    def test_target_exact(self):
        self.assertEqual(s.target(100, 0, 1, 1.28), 200)
        self.assertEqual(s.target(100, 0, 4, 0), 500)
    def test_target_monotone(self):
        self.assertLess(s.target(100,25,4,0), s.target(100,25,4,1.28))
        self.assertLess(s.target(100,25,4,1.28), s.target(100,25,4,2.326))
    def test_policy_targets(self):
        history = [100]*20+[150]*3
        a = s.profile_target('trend_response',history,[100]*20,1)
        b = s.profile_target('service_buffer',history,[100]*20,1)
        c = s.profile_target('plan_anchored',history,[100]*20,1)
        self.assertGreater(a,b)
        self.assertEqual(c,200)
    def test_same_constant_demand_target(self):
        for p in s.PROFILES:
            self.assertEqual(s.profile_target(p,[100]*20,[100]*20,1),200)
    def test_unknown_profile(self):
        with self.assertRaises(ValueError):s.profile_target('human',[1]*20,[1]*20,1)
    def test_trigger_at_change(self):
        self.assertFalse(s.review_trigger([100]*20))
        self.assertTrue(s.review_trigger([100]*20+[200]*3))
    def test_no_trigger_from_future(self):
        history=[100]*20
        self.assertEqual(s.review_trigger(history),False)
    def test_order_caps(self):
        c=s.Config()
        self.assertEqual(s.order_quantity(2000,500,20000,c),400)
        self.assertEqual(s.order_quantity(2000,1195,20000,c),5)
        self.assertEqual(s.order_quantity(2000,0,2019,c),0)
        self.assertEqual(s.order_quantity(2000,0,2020,c),1)
    def test_no_order_when_stock_sufficient(self):
        self.assertEqual(s.order_quantity(100,101,20000,s.Config()),0)
    def test_no_order_when_cash_negative(self):
        self.assertEqual(s.order_quantity(100,0,-100,s.Config()),0)
    def test_input_negative_demand(self):
        with self.assertRaises(ValueError):s.simulate([100]*20,[-1],s.Config())
    def test_input_noninteger_demand(self):
        with self.assertRaises(ValueError):s.simulate([100]*20,[1.5],s.Config())
    def test_input_nonfinite(self):
        with self.assertRaises(ValueError):s.simulate([100]*20,[float('nan')],s.Config())
    def test_config_lead(self):
        with self.assertRaises(ValueError):s.Config(lead=0)
    def test_baseline_identity(self):
        c=s.Config();a,la=s.simulate([100]*20,[100]*12,c)
        b,lb=s.simulate([100]*20,[100]*12,c)
        self.assertEqual(a,b);self.assertEqual(la,lb)
    def test_mass_cash_ledger(self):
        c=s.Config();out,rows=s.simulate([100]*20,[0,300,0,400,100,200],c)
        self.assertEqual(out['initial_stock']+out['orders']-out['sold'],out['end_stock']+out['end_pipeline'])
        cash=c.initial_cash + c.price*out['sold']-c.unit_cost*out['orders']-out['holding_cost']-out['review_cost']
        self.assertAlmostEqual(cash,out['end_cash'])
        self.assertAlmostEqual(out['net_surplus'],cash+out['terminal_credit']-c.initial_cash-out['initial_stock']*c.unit_cost)
    def test_arrivals_not_same_period(self):
        c=s.Config(lead=1)
        out,rows=s.simulate([100]*20,[300]*4,c)
        self.assertEqual(rows[1]['arrivals'],0)
        self.assertEqual(rows[2]['arrivals'],rows[1]['order'])
    def test_caps_all_periods(self):
        out,rows=s.simulate([100]*20,[300]*60,s.Config())
        for r in rows:
            self.assertLessEqual(r['order'],400)
            self.assertLessEqual(r['inventory_position_after_order'],1200)
            self.assertGreaterEqual(r['on_hand_end'],0)
            self.assertGreaterEqual(r['lost'],0)
            self.assertLessEqual(r['sold'],r['demand'])
    def test_initial_zero(self):
        out,rows=s.simulate([0]*20,[0]*5,s.Config())
        self.assertEqual(out['net_surplus'],0)
        self.assertIsNone(out['fill_rate'])
    def test_fee_and_budget(self):
        out,rows=s.simulate([100]*20,[200]*30+[50]*30,s.Config(),profile='trend_response',delay=2,fee=25)
        requested=[r['t'] for r in rows if r['review_requested']]
        self.assertLessEqual(len(requested),4)
        self.assertTrue(all(b-a>=6 for a,b in zip(requested,requested[1:])))
        self.assertEqual(out['review_cost'],25*len(requested))
        for i in requested:
            self.assertEqual(rows[i+2]['delivered_request_t'],i)
    def test_same_schedule_profiles(self):
        schedules=[]
        for p in s.PROFILES:
            _,rows=s.simulate([100]*20,[200]*30+[50]*30,s.Config(),profile=p)
            schedules.append([r['t'] for r in rows if r['review_requested']])
        self.assertTrue(all(x==schedules[0] for x in schedules))
    def test_past_prefix_unchanged(self):
        a,ra=s.simulate([100]*20,[200]*15+[50]*15,s.Config(),profile='trend_response')
        b,rb=s.simulate([100]*20,[200]*15+[300]*15,s.Config(),profile='trend_response')
        self.assertEqual(ra[:15],rb[:15])
    def test_inactive_profile_equals_baseline(self):
        for p in s.PROFILES:
            a,_=s.simulate([100]*20,[100]*60,s.Config())
            b,_=s.simulate([100]*20,[100]*60,s.Config(),profile=p)
            self.assertEqual(a['net_surplus'],b['net_surplus'])
            self.assertEqual(b['review_count'],0)
    def test_generated_reproducible(self):
        a=s.generate_paths(41000);b=s.generate_paths(41000)
        self.assertEqual(a,b)
    def test_generated_prefix_shared(self):
        x=s.generate_paths(41000)
        self.assertEqual(len(x['train']),20)
        self.assertEqual(len(x['stationary']),60)
        self.assertEqual(x['stationary'][:20],x['upshift'][:20])
    def test_unknown_regime_absent_from_policy_input(self):
        import inspect
        self.assertNotIn('regime',inspect.signature(s.profile_target).parameters)
    def test_review_invalid_delay(self):
        with self.assertRaises(ValueError):s.simulate([100]*20,[100]*2,s.Config(),profile='cash_buffer',delay=-1)
    def test_review_invalid_fee(self):
        with self.assertRaises(ValueError):s.simulate([100]*20,[100]*2,s.Config(),fee=-1)

if __name__=='__main__':unittest.main()
