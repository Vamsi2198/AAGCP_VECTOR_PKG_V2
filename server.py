#!/usr/bin/env python3
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

from aagcp_vector.policy import PolicyEngine, AuditChain
from aagcp_vector.store import HashingEmbedder, InMemoryVectorStore
from aagcp_vector.vault import PseudonymVault
from aagcp_vector.control_plane import VectorGovernanceControlPlane

ROOT = Path(__file__).parent
OUT = ROOT / "demo_output"
OUT.mkdir(exist_ok=True)
POLICY = str(ROOT / "policies" / "default_policy.yaml")
DEMO_SECRET = b"aagcp-vector-demo-secret-32bytes!"

DOCS = {
    "rec_001": "Patient Ramesh Iyer, Aadhaar 4521 8834 9912, phone +91 9845012345, "
               "MRN-100234, diagnosed with Type 2 Diabetes. Treating physician Dr. Anil Kumar. "
               "Follow-up: metformin titration, HbA1c review in 12 weeks.",
    "rec_002": "Patient Priya Sharma, PAN ABCDE1234F, email priya.sharma@gmail.com, "
               "MRN-100871, diagnosed with Type 2 Diabetes with early nephropathy. "
               "Dr. Anil Kumar recommends SGLT2 inhibitor and renal panel.",
    "rec_003": "Patient Arjun Mehta, Aadhaar 7733 1029 5566, phone 9867554321, "
               "MRN-101422, presented with atrial fibrillation. Dr. Sunita Rao "
               "initiated anticoagulation, cardiology follow-up in 4 weeks.",
    "rec_004": "Patient Kavya Nair, email kavya.n@yahoo.in, MRN-102001, "
               "hypertension well controlled. Dr. Sunita Rao continued amlodipine.",
    "rec_005": "Patient Vikram Reddy, Aadhaar 9911 2233 4455, phone +91 9123456780, "
               "MRN-102388, Type 2 Diabetes with peripheral neuropathy. "
               "Dr. Anil Kumar adjusted insulin regimen, podiatry referral made.",
    "rec_006": "Patient Ananya Das, PAN FGHIJ5678K, MRN-102990, migraine with aura. "
               "Dr. Sunita Rao prescribed prophylaxis, neurology review scheduled.",
}
LEXICON = [
    "Ramesh Iyer", "Priya Sharma", "Arjun Mehta", "Kavya Nair",
    "Vikram Reddy", "Ananya Das", "Anil Kumar", "Sunita Rao"
]
PROBES = [
    "patients diagnosed with type 2 diabetes",
    "cardiology and heart rhythm cases",
    "who is treated by Dr. Anil Kumar"
]

embedder = HashingEmbedder(dim=512)
plane = VectorGovernanceControlPlane(
    embedder=embedder,
    store=InMemoryVectorStore(),
    vault=PseudonymVault(str(OUT / "vault.json"), secret=DEMO_SECRET),
    policy=PolicyEngine(POLICY),
    audit=AuditChain(str(OUT / "audit.jsonl")),
    collection="health_records",
)
plane_ready = False


def ingest_documents():
    global plane_ready
    if plane_ready:
        return {
            "success": True,
            "message": "Documents already ingested.",
            "count": len(DOCS),
        }

    for doc_id, text in DOCS.items():
        plane.ingest(doc_id, text, person_lexicon=LEXICON, probe_queries=PROBES)

    plane_ready = True
    return {
        "success": True,
        "message": "Demo documents ingested successfully.",
        "count": len(DOCS),
    }


class DemoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/":
            self.path = "/ui.html"
            return super().do_GET()
        if route == "/health":
            return self.send_json({"status": "ok", "message": "server running"})
        if route == "/audit":
            return self.send_json({
                "success": True,
                "stats": plane.stats,
                "audit_valid": plane.audit.verify(),
                "policy_version": plane.policy.version,
            })
        return super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        body = self._read_json()
        if route == "/ingest":
            result = ingest_documents()
            return self.send_json(result)
        if route == "/query":
            role = body.get("role", "ANALYST_ROLE")
            query_text = body.get("query", "patients diagnosed with type 2 diabetes")
            result = plane.query(role, query_text, top_k=3)
            return self.send_json(result)
        if route == "/erase":
            subject = body.get("subject", "Ramesh Iyer")
            requester = body.get("requester", "dpo@client.example")
            result = plane.erase_subject(subject, requester=requester)
            return self.send_json(result)
        self.send_error(404, "Not Found")

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length == 0:
            return {}
        data = self.rfile.read(length).decode("utf-8")
        return json.loads(data)

    def send_json(self, payload, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(payload, indent=2).encode("utf-8"))

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server_address = ("127.0.0.1", 8000)
    print(f"Starting AAGCP Vector UI server at http://{server_address[0]}:{server_address[1]}")
    print("Open the browser and click buttons to exercise the demo endpoints.")
    httpd = HTTPServer(server_address, DemoHandler)
    httpd.serve_forever()
