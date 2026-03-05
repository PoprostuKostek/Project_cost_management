"""KSeF invoice downloader — connects to the production KSeF API and downloads invoices."""
import base64
import datetime
import json
import logging
import os
import time

import requests
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.padding import OAEP, MGF1

# ------------------- configuration -------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_URL = "https://api.ksef.mf.gov.pl/v2"

logger = logging.getLogger(__name__)


def load_config():
    """Load KSeF settings from data/ksef_config.json."""
    path = os.path.join(PROJECT_ROOT, "data", "ksef_config.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def resolve_path(path):
    """Resolve a relative config path against the project root."""
    if path and not os.path.isabs(path):
        return os.path.join(PROJECT_ROOT, path)
    return path


cfg = load_config()

USE_TOKEN_AUTH = cfg.get("USE_TOKEN_AUTH", True)
TOKEN = cfg.get("TOKEN", "")
NIP = cfg.get("NIP", "")
SUBJECT_TYPE = cfg.get("SUBJECT_TYPE", "Subject2")
KEY_FILE = resolve_path(cfg.get("KEY_FILE"))
CERT_FILE = resolve_path(cfg.get("CERT_FILE"))

SAVE_DIR = "faktury_ksef"
os.makedirs(SAVE_DIR, exist_ok=True)


# ------------------- errors -------------------

class KSeFError(Exception):
    """Raised when a KSeF API call fails."""
    def __init__(self, message, status_code=None, response_data=None):
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(self.message)


# ------------------- api client -------------------

class KSeFSession:
    """Manages a single authenticated session against the KSeF v2 API."""

    def __init__(self, token=None, key_file=None, cert_file=None, key_password=None,
                 timeout=30):
        self._token = token
        self._key_file = key_file
        self._cert_file = cert_file
        self._key_password = key_password.encode("utf-8") if key_password else None
        self._timeout = timeout

        self._auth_token = None
        self._access_token = None
        self._refresh_token = None
        self._ref_number = None
        self._cached_pub_key = None

    # --- http helpers ---

    def _headers(self, authenticated=True):
        """Build request headers, optionally adding the session bearer token."""
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if authenticated:
            bearer = self._access_token or self._auth_token
            if bearer:
                h["Authorization"] = f"Bearer {bearer}"
        return h

    def _request(self, method, endpoint, body=None, authenticated=True, accept="application/json"):
        """Send an HTTP request to the KSeF API and return parsed response."""
        url = f"{API_URL}{endpoint}"
        h = self._headers(authenticated)
        h["Accept"] = accept

        logger.info("KSeF %s %s", method, url)

        try:
            resp = requests.request(method, url, headers=h, json=body if method != "GET" else None,
                                    timeout=self._timeout)
        except requests.RequestException as exc:
            raise KSeFError(f"Connection error: {exc}")

        logger.info("KSeF response: %d", resp.status_code)

        if resp.status_code >= 400:
            msg = f"HTTP {resp.status_code}"
            data = {}
            try:
                data = resp.json()
                detail = (data.get("exception", {})
                              .get("exceptionDetailList", [{}])[0]
                              .get("exceptionDescription"))
                if detail:
                    msg = detail
            except Exception:
                data = {"raw": resp.text[:500]}
            raise KSeFError(msg, resp.status_code, data)

        if not resp.text:
            return {}

        ct = resp.headers.get("Content-Type", "")
        if "application/json" in ct:
            return resp.json()
        try:
            return resp.json()
        except json.JSONDecodeError:
            return {"raw_content": resp.text}

    # --- auth helpers ---

    def _get_challenge(self, nip):
        """Request an auth challenge for the given NIP."""
        return self._request(
            "POST", "/auth/challenge",
            body={"contextIdentifier": {"type": "onip", "identifier": nip}},
            authenticated=False,
        )

    def _fetch_public_key(self):
        """Download the KSeF RSA public key certificate (cached)."""
        if self._cached_pub_key:
            return self._cached_pub_key

        resp = self._request("GET", "/security/public-key-certificates", authenticated=False)
        certs = resp if isinstance(resp, list) else resp.get("certificates", [])
        if not certs:
            raise KSeFError("No public-key certificates returned by KSeF")

        pem = None
        for c in certs:
            if c.get("status", "").lower() in ("active", ""):
                pem = c.get("certificate") or c.get("publicKey")
                if pem:
                    break
        if not pem:
            pem = certs[0].get("certificate") or certs[0].get("publicKey")
        if not pem:
            raise KSeFError("Could not extract public key from KSeF", response_data=resp)

        if not pem.startswith("-----"):
            pem = f"-----BEGIN CERTIFICATE-----\n{pem}\n-----END CERTIFICATE-----"
        self._cached_pub_key = pem
        return pem

    def _encrypt_token(self, token, timestamp_ms):
        """RSA-OAEP encrypt the token|timestamp string with the KSeF public key."""
        pem = self._fetch_public_key()
        try:
            if "BEGIN CERTIFICATE" in pem:
                pub = x509.load_pem_x509_certificate(pem.encode(), default_backend()).public_key()
            else:
                pub = serialization.load_pem_public_key(pem.encode(), default_backend())
        except Exception as exc:
            raise KSeFError(f"Failed to load public key: {exc}")

        encrypted = pub.encrypt(
            f"{token}|{timestamp_ms}".encode("utf-8"),
            OAEP(mgf=MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        return base64.b64encode(encrypted).decode("utf-8")

    def _build_auth_xml(self, challenge, nip):
        """Build the AuthTokenRequest XML document for XAdES signing."""
        xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<AuthTokenRequest '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns="http://ksef.mf.gov.pl/auth/token/2.0">'
            f'<Challenge>{challenge}</Challenge>'
            '<ContextIdentifier>'
            f'<Nip>{nip}</Nip>'
            '</ContextIdentifier>'
            '<SubjectIdentifierType>certificateSubject</SubjectIdentifierType>'
            '</AuthTokenRequest>'
        )
        return xml.encode("utf-8")

    def _sign_xml(self, xml_bytes):
        """Sign XML with XAdES enveloped signature using the configured key/cert."""
        from lxml import etree
        from signxml import methods as signxml_methods
        from signxml.xades import XAdESSigner, XAdESDataObjectFormat

        if not self._key_file:
            raise KSeFError("No private key file configured (KEY_FILE)")
        if not self._cert_file:
            raise KSeFError("No certificate file configured (CERT_FILE)")

        with open(self._key_file, "rb") as f:
            key_pem = f.read()
        with open(self._cert_file, "rb") as f:
            cert_data = f.read()

        try:
            cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        except Exception:
            cert = x509.load_der_x509_certificate(cert_data, default_backend())

        cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")

        from cryptography.hazmat.primitives.asymmetric import rsa, ec
        pub = cert.public_key()
        sig_alg = "ecdsa-sha256" if isinstance(pub, ec.EllipticCurvePublicKey) else "rsa-sha256"

        fmt = XAdESDataObjectFormat(Description="Logowanie do KSeF", MimeType="application/xml")
        signer = XAdESSigner(method=signxml_methods.enveloped, signature_algorithm=sig_alg,
                             data_object_format=fmt)

        params = {"key": key_pem, "cert": cert_pem}
        if self._key_password:
            params["passphrase"] = self._key_password

        root = etree.fromstring(xml_bytes)
        return etree.tostring(signer.sign(root, **params))

    def _wait_and_redeem(self):
        """Poll auth status until ready, then exchange for an access token."""
        for attempt in range(30):
            status = self._request("GET", f"/auth/{self._ref_number}")
            code = (status.get("status", {}).get("code")
                    or status.get("processingCode"))
            if code == 200:
                break
            if code == 100:
                logger.info("Auth in progress (%d/30)…", attempt + 1)
                time.sleep(1)
                continue
            desc = status.get("status", {}).get("description", "Unknown")
            raise KSeFError(f"Auth error: code {code} — {desc}", response_data=status)
        else:
            raise KSeFError("Auth timeout — no response after 30 attempts")

        resp = self._request("POST", "/auth/token/redeem")
        at = resp.get("accessToken")
        rt = resp.get("refreshToken")
        self._access_token = at.get("token") if isinstance(at, dict) else at
        self._refresh_token = rt.get("token") if isinstance(rt, dict) else rt

    # --- public api ---

    def open_session(self, nip, use_token_auth=True):
        """Authenticate with KSeF and obtain an access token."""
        challenge_resp = self._get_challenge(nip)
        challenge = challenge_resp.get("challenge")
        ts = challenge_resp.get("timestampMs")
        if not challenge or ts is None:
            raise KSeFError("Missing challenge/timestamp", response_data=challenge_resp)

        if use_token_auth:
            encrypted = self._encrypt_token(self._token, ts)
            resp = self._request(
                "POST", "/auth/ksef-token",
                body={
                    "challenge": challenge,
                    "contextIdentifier": {"type": "Nip", "value": nip},
                    "encryptedToken": encrypted,
                },
                authenticated=False,
            )
        else:
            xml = self._build_auth_xml(challenge, nip)
            signed = self._sign_xml(xml)
            url = f"{API_URL}/auth/xades-signature"
            headers = {"Content-Type": "application/xml", "Accept": "application/json"}
            r = requests.post(url, data=signed, headers=headers, timeout=self._timeout)
            if r.status_code >= 400:
                msg = f"HTTP {r.status_code}"
                data = {}
                try:
                    data = r.json()
                    d = data.get("exception", {}).get("exceptionDetailList", [{}])[0]
                    msg = d.get("exceptionDescription", msg)
                except Exception:
                    data = {"raw": r.text[:500]}
                raise KSeFError(msg, r.status_code, data)
            resp = r.json()

        self._auth_token = resp.get("authenticationToken", {}).get("token")
        self._ref_number = resp.get("referenceNumber")
        if not self._auth_token:
            raise KSeFError("No auth token received", response_data=resp)

        self._wait_and_redeem()

    def close_session(self):
        """Terminate the current KSeF session."""
        if not self._access_token:
            raise KSeFError("No active session")
        self._request("DELETE", "/auth/sessions/current")
        self._auth_token = self._access_token = self._refresh_token = self._ref_number = None

    def query_invoices(self, subject_type="Subject2", date_from=None, date_to=None,
                       page_size=100, page_offset=0):
        """Query invoice metadata for a date range."""
        if not self._access_token:
            raise KSeFError("No active session")

        if date_to is None:
            date_to = datetime.date.today()
        if date_from is None:
            date_from = date_to - datetime.timedelta(days=30)

        max_span = datetime.timedelta(days=90)
        if (date_to - date_from) > max_span:
            date_from = date_to - max_span

        body = {
            "subjectType": subject_type,
            "dateRange": {
                "dateType": "Invoicing",
                "from": f"{date_from.isoformat()}T00:00:00",
                "to": f"{date_to.isoformat()}T23:59:59",
            },
        }
        qs = f"?pageSize={min(page_size, 250)}&pageOffset={page_offset}"
        return self._request("POST", f"/invoices/query/metadata{qs}", body=body)

    def get_invoice_xml(self, ksef_number):
        """Download raw XML of a single invoice by its KSeF number."""
        if not self._access_token:
            raise KSeFError("No active session")

        url = f"{API_URL}/invoices/ksef/{ksef_number}"
        h = self._headers()
        h["Accept"] = "application/octet-stream"
        resp = requests.get(url, headers=h, timeout=self._timeout)
        if resp.status_code >= 400:
            raise KSeFError(f"Error downloading {ksef_number}: {resp.status_code}",
                            resp.status_code)
        return resp.content


# ------------------- download logic -------------------

def download_all_invoices(token=None, nip=None, environment=None,
                          subject_type=None, date_from=None, date_to=None,
                          save_dir=None, key_file=None, cert_file=None,
                          key_password=None, use_token_auth=None,
                          skip_ksef_numbers=None, progress_callback=None):
    """Download all invoices from the KSeF production API.

    Args:
        token: KSeF authorization token.
        nip: Entity NIP number.
        environment: Kept for compatibility (only 'prod' is supported).
        subject_type: 'Subject1' (issued) or 'Subject2' (received).
        date_from: Start date.
        date_to: End date.
        save_dir: Directory for downloaded XML files.
        key_file: Private key path for seal auth.
        cert_file: Certificate path for seal auth.
        key_password: Private key password (runtime only).
        use_token_auth: True for token auth, False for key/seal auth.
        skip_ksef_numbers: Set of KSeF numbers already in the database.
        progress_callback: Called with the count of downloaded invoices (or -1 when waiting).
    """
    final_token = token or TOKEN
    final_nip = nip or NIP
    final_subject = subject_type or SUBJECT_TYPE
    final_date_from = date_from
    final_date_to = date_to
    final_dir = save_dir or SAVE_DIR
    final_key = key_file or KEY_FILE
    final_cert = cert_file or CERT_FILE
    final_use_token = use_token_auth if use_token_auth is not None else USE_TOKEN_AUTH

    if final_use_token and not final_token:
        raise ValueError("No token provided")
    if not final_use_token:
        if not final_key:
            raise ValueError("No key file provided")
        if not final_cert:
            raise ValueError("No certificate file provided")
    if not final_nip:
        raise ValueError("No NIP provided")

    session = KSeFSession(
        token=final_token, key_file=final_key, cert_file=final_cert,
        key_password=key_password,
    )

    method_label = "token" if final_use_token else "private key (seal)"
    print(f"Connecting to KSeF (method: {method_label})…")
    print(f"NIP: {final_nip}")

    session.open_session(final_nip, use_token_auth=final_use_token)
    print(f"Session opened.")

    # KSeF hourly rate limits (with safety margin)
    get_limit, post_limit = 60, 18
    get_count = post_count = 0
    hour_start = time.time()

    def _wait_if_rate_limited(kind):
        nonlocal get_count, post_count, hour_start
        elapsed = time.time() - hour_start
        if elapsed >= 3600:
            get_count = post_count = 0
            hour_start = time.time()
            return
        hit = (kind == "GET" and get_count >= get_limit) or \
              (kind == "POST" and post_count >= post_limit)
        if hit:
            wait = int(3600 - elapsed) + 5
            print(f"Hourly {kind} limit reached. Waiting {wait}s…")
            if progress_callback:
                progress_callback(-1)
            time.sleep(wait)
            get_count = post_count = 0
            hour_start = time.time()

    time.sleep(5)

    try:
        offset = 0
        total = 0

        while True:
            _wait_if_rate_limited("POST")
            try:
                result = session.query_invoices(
                    subject_type=final_subject,
                    date_from=final_date_from,
                    date_to=final_date_to,
                    page_size=100,
                    page_offset=offset,
                )
                post_count += 1
            except KSeFError as exc:
                if "walidacji" in exc.message.lower() or "validation" in exc.message.lower():
                    if total == 0:
                        print("No invoices found.")
                    break
                raise

            invoices = result.get("invoices", [])
            if not invoices:
                if total == 0:
                    print("No invoices found.")
                break

            time.sleep(3)

            for inv in invoices:
                ksef_num = inv.get("ksefNumber")
                if not ksef_num:
                    continue

                if skip_ksef_numbers and ksef_num in skip_ksef_numbers:
                    print(f"Skipped (in database): {ksef_num}")
                    continue

                safe_name = ksef_num.replace("/", "_").replace("\\", "_")
                file_path = os.path.join(final_dir, f"{safe_name}.xml")
                if os.path.exists(file_path):
                    print(f"Skipped (file exists): {ksef_num}")
                    continue

                for retry in range(3):
                    try:
                        _wait_if_rate_limited("GET")
                        xml_raw = session.get_invoice_xml(ksef_num)
                        get_count += 1

                        with open(file_path, "wb") as f:
                            f.write(xml_raw)

                        total += 1
                        print(f"Saved: {ksef_num}")
                        if progress_callback:
                            progress_callback(total)
                        break
                    except KSeFError as exc:
                        if exc.status_code == 429 and retry < 2:
                            wait = max(int(3600 - (time.time() - hour_start)) + 5, 60)
                            print(f"Rate limit (429) for {ksef_num}, waiting {wait}s…")
                            time.sleep(wait)
                            get_count = post_count = 0
                            hour_start = time.time()
                        else:
                            print(f"Error downloading {ksef_num}: {exc.message}")
                            break

                time.sleep(1)

            offset += 100
            print(f"Downloaded so far: {total}")

    finally:
        print("\nTerminating session…")
        try:
            session.close_session()
            print("Session closed.")
        except KSeFError as exc:
            print(f"Error closing session: {exc.message}")

    print(f"\nDone. Downloaded {total} invoices to: {final_dir}/")
