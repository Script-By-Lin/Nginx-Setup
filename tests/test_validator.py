"""Unit tests for validation utilities."""

import shutil
import sys
from utils.validator import DomainValidator, PathValidator, PortValidator


def test_port_validator():
    assert PortValidator.is_valid_port(80) is True
    assert PortValidator.is_valid_port(8000) is True
    assert PortValidator.is_valid_port(65535) is True
    assert PortValidator.is_valid_port(0) is False
    assert PortValidator.is_valid_port(70000) is False
    assert PortValidator.is_valid_port("80") is False


def test_domain_validator():
    assert DomainValidator.is_valid_domain("example.com") is True
    assert DomainValidator.is_valid_domain("api.sub.example.co.uk") is True
    assert DomainValidator.is_valid_domain("localhost") is True
    assert DomainValidator.is_valid_domain("invalid_domain") is False
    assert DomainValidator.is_valid_domain("http://example.com") is False

    assert DomainValidator.is_valid_ip("127.0.0.1") is True
    assert DomainValidator.is_valid_ip("192.168.1.1") is True
    assert DomainValidator.is_valid_ip("999.999.999.999") is False

    assert DomainValidator.is_valid_route_path("/") is True
    assert DomainValidator.is_valid_route_path("/api1/") is True
    assert DomainValidator.is_valid_route_path("/api/v2/docs") is True
    assert DomainValidator.is_valid_route_path("api") is False
    assert DomainValidator.is_valid_route_path("/api; drop table") is False


def test_path_validator():
    # Python executable should be found
    valid, msg = PathValidator.validate_executable_path(sys.executable)
    assert valid is True

    # Empty string should fail
    valid, msg = PathValidator.validate_executable_path("")
    assert valid is False

    # Non-existent path
    valid, msg = PathValidator.validate_executable_path("/non/existent/path/binary_xyz")
    assert valid is False
