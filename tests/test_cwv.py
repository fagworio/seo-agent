"""Tests for Core Web Vitals checks + CrUX/PSI value extraction."""

from hermes_seo_agent.checks.cwv import cwv_findings
from hermes_seo_agent.connectors.crux import CruxClient
from hermes_seo_agent.connectors.pagespeed import PageSpeedClient


def test_cwv_findings_pass():
    assert cwv_findings("https://x.com/", {"lcp": 1.8, "cls": 0.05, "inp": 120}) == []


def test_cwv_findings_fail():
    findings = cwv_findings("https://x.com/", {"lcp": 3.1, "cls": 0.2, "inp": 350})
    rules = {f["rule_id"] for f in findings}
    assert rules == {"cwv_lcp_poor", "cwv_cls_poor", "cwv_inp_poor"}
    assert all(f["severity"] == "medium" for f in findings)


def test_crux_values_extraction():
    """CrUX returns LCP/INP p75 as numbers (ms) and CLS as a STRING."""
    record = {
        "record": {
            "metrics": {
                "largest_contentful_paint": {"percentiles": {"p75": 2800}},   # ms, number
                "cumulative_layout_shift": {"percentiles": {"p75": "0.31"}},  # string!
                "interaction_to_next_paint": {"percentiles": {"p75": 400}},   # ms, number
            }
        }
    }
    values = CruxClient.cwv_values(record)
    assert values["lcp"] == 2.8    # 2800ms -> 2.8s
    assert values["cls"] == 0.31   # coerced from string
    assert values["inp"] == 400.0  # ms, unchanged
    assert {f["rule_id"] for f in cwv_findings("https://x.com/", values)} == {
        "cwv_lcp_poor", "cwv_cls_poor", "cwv_inp_poor"
    }


def test_crux_good_values_no_findings():
    """Real-ish CrUX values within thresholds must NOT produce findings."""
    record = {
        "record": {
            "metrics": {
                "largest_contentful_paint": {"percentiles": {"p75": 1572}},   # 1.57s OK
                "cumulative_layout_shift": {"percentiles": {"p75": 0.05}},
                "interaction_to_next_paint": {"percentiles": {"p75": 134}},   # 134ms OK
            }
        }
    }
    values = CruxClient.cwv_values(record)
    assert cwv_findings("https://x.com/", values) == []


def test_psi_values_extraction():
    result = {
        "lighthouseResult": {
            "audits": {
                "largest-contentful-paint": {"numericValue": 3100},
                "cumulative-layout-shift": {"numericValue": 0.15},
                "interaction-to-next-paint": {"numericValue": 250},
            }
        }
    }
    values = PageSpeedClient.cwv_values(result)
    assert values["lcp"] == 3.1
    assert values["cls"] == 0.15
    assert values["inp"] == 250  # ms already from PSI
