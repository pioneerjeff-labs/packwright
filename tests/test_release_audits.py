import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_zero_network", ROOT / "scripts" / "audit_zero_network.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ZeroNetworkAuditTest(unittest.TestCase):
    def test_python_positive_and_negative_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.py"
            path.write_text("import requests as r\nr.get('https://example.test')\n", encoding="utf-8")
            self.assertTrue(audit.audit_python(path))
            path.write_text("value = 'https://example.test'\n", encoding="utf-8")
            self.assertEqual(audit.audit_python(path), [])

    def test_landing_blocks_auto_load_but_allows_links(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><a href="https://example.test">link</a>', encoding="utf-8")
            self.assertEqual(audit.audit_landing(path), [])
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><script src="https://example.test/x.js"></script>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))

    def test_landing_detects_css_and_javascript_network_calls(self):
        csp = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><style>x{{background:url(https://example.test/x)}}</style>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))
            path.write_text(f'<meta http-equiv="Content-Security-Policy" content="{csp}"><script>fetch("/beacon")</script>', encoding="utf-8")
            self.assertTrue(audit.audit_landing(path))


if __name__ == "__main__": unittest.main()
