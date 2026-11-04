"""Lab PKI generation with the ``cryptography`` library (no custom crypto).

Creates, under results/certs/:

* ``lab-ca``       - the CA the RouteResQ client trusts
* ``server``       - certificate for localhost / 127.0.0.1 signed by lab-ca (valid)
* ``rogue-ca`` + ``rogue-server`` - same names, signed by a CA the client does NOT trust
* ``wrong-host``   - signed by lab-ca but issued for ``wrong-host.example`` (name mismatch)

The private keys are for local lab use only.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from common.paths import CERT_DIR


@dataclass
class LabPKI:
    dir: Path
    ca_cert: Path
    server_cert: Path
    server_key: Path
    rogue_ca_cert: Path
    rogue_server_cert: Path
    rogue_server_key: Path
    wrong_host_cert: Path
    wrong_host_key: Path


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RouteResQ Lab"),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def _write_key(key, path: Path) -> None:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))


def _write_cert(cert: x509.Certificate, path: Path) -> None:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _ca(cn: str, days: int):
    key = _key()
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn)).issuer_name(_name(cn))
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                     content_commitment=False, key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _leaf(cn: str, dns_names: list[str], ips: list[str], ca_key, ca_cert, days: int):
    key = _key()
    now = dt.datetime.now(dt.timezone.utc)
    san = [x509.DNSName(n) for n in dns_names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(cn)).issuer_name(ca_cert.subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _paths(d: Path) -> LabPKI:
    return LabPKI(d, d / "lab-ca.pem", d / "server.pem", d / "server.key", d / "rogue-ca.pem",
                  d / "rogue-server.pem", d / "rogue-server.key", d / "wrong-host.pem", d / "wrong-host.key")


def generate_lab_pki(directory: Path = CERT_DIR, days: int = 30) -> LabPKI:
    directory.mkdir(parents=True, exist_ok=True)
    p = _paths(directory)
    ca_key, ca = _ca("RouteResQ Lab CA", days)
    _write_cert(ca, p.ca_cert)
    k, c = _leaf("localhost", ["localhost"], ["127.0.0.1"], ca_key, ca, days)
    _write_cert(c, p.server_cert)
    _write_key(k, p.server_key)
    rk, rca = _ca("Untrusted Rogue CA", days)
    _write_cert(rca, p.rogue_ca_cert)
    k, c = _leaf("localhost", ["localhost"], ["127.0.0.1"], rk, rca, days)
    _write_cert(c, p.rogue_server_cert)
    _write_key(k, p.rogue_server_key)
    k, c = _leaf("wrong-host.example", ["wrong-host.example"], [], ca_key, ca, days)
    _write_cert(c, p.wrong_host_cert)
    _write_key(k, p.wrong_host_key)
    return p


def ensure_lab_pki(directory: Path = CERT_DIR) -> LabPKI:
    """Return existing certificates, regenerating them if missing or expiring within a day."""
    p = _paths(directory)
    files = [p.ca_cert, p.server_cert, p.server_key, p.rogue_server_cert, p.rogue_server_key,
             p.wrong_host_cert, p.wrong_host_key]
    if all(f.exists() for f in files):
        cert = x509.load_pem_x509_certificate(p.server_cert.read_bytes())
        if cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1):
            return p
    return generate_lab_pki(directory)
