"""Create a self-signed HTTPS certificate for the intranet server.

  python scripts/make_cert.py hop.local [other-name ...]

Better: ask IT for a certificate from the company's internal CA, so browsers trust it without warnings.
"""
import datetime as dt
import ipaddress
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

names = sys.argv[1:] or ["localhost"]
os.makedirs("certs", exist_ok=True)
key = ec.generate_private_key(ec.SECP256R1())
alt = []
for n in names + ["localhost"]:
    try:
        alt.append(x509.IPAddress(ipaddress.ip_address(n)))
    except ValueError:
        alt.append(x509.DNSName(n))
subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0]), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Hop (internal)")])
now = dt.datetime.now(dt.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(list(dict.fromkeys(alt))), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
with open("certs/server.key", "wb") as f:
    f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
os.chmod("certs/server.key", 0o600)
with open("certs/server.crt", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
print("Created certs/server.crt and certs/server.key for:", ", ".join(names))
