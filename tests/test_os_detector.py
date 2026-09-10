"""Unit tests for OS Detector."""

import tempfile
from pathlib import Path
from core.os_detector import OSDetector
from models.server_config import OSFamily, PackageManager


def create_mock_os_release(content: str) -> str:
    f = tempfile.NamedTemporaryFile("w", delete=False)
    f.write(content)
    f.close()
    return f.name


def test_detect_ubuntu():
    mock_content = """NAME="Ubuntu"
VERSION="22.04.4 LTS (Jammy Jellyfish)"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME="Ubuntu 22.04.4 LTS"
VERSION_ID="22.04"
"""
    path = create_mock_os_release(mock_content)
    try:
        detector = OSDetector(os_release_path=path)
        info = detector.detect()
        assert info.family == OSFamily.DEBIAN
        assert info.package_manager == PackageManager.APT
        assert info.nginx_conf_dir == "/etc/nginx/sites-available"
        assert info.use_symlinks is True
        assert info.nginx_sites_enabled_dir == "/etc/nginx/sites-enabled"
    finally:
        Path(path).unlink(missing_ok=True)


def test_detect_rocky():
    mock_content = """NAME="Rocky Linux"
VERSION="9.3 (Blue Onyx)"
ID="rocky"
ID_LIKE="rhel centos fedora"
VERSION_ID="9.3"
PRETTY_NAME="Rocky Linux 9.3 (Blue Onyx)"
"""
    path = create_mock_os_release(mock_content)
    try:
        detector = OSDetector(os_release_path=path)
        info = detector.detect()
        assert info.family == OSFamily.RHEL
        assert info.package_manager == PackageManager.DNF
        assert info.nginx_conf_dir == "/etc/nginx/conf.d"
        assert info.use_symlinks is False
    finally:
        Path(path).unlink(missing_ok=True)


def test_detect_arch():
    mock_content = """NAME="Arch Linux"
PRETTY_NAME="Arch Linux"
ID=arch
BUILD_ID=rolling
"""
    path = create_mock_os_release(mock_content)
    try:
        detector = OSDetector(os_release_path=path)
        info = detector.detect()
        assert info.family == OSFamily.ARCH
        assert info.package_manager == PackageManager.PACMAN
        assert info.nginx_conf_dir == "/etc/nginx/conf.d"
    finally:
        Path(path).unlink(missing_ok=True)


def test_detect_alpine():
    mock_content = """NAME="Alpine Linux"
ID=alpine
VERSION_ID=3.19.0
PRETTY_NAME="Alpine Linux v3.19"
"""
    path = create_mock_os_release(mock_content)
    try:
        detector = OSDetector(os_release_path=path)
        info = detector.detect()
        assert info.family == OSFamily.ALPINE
        assert info.package_manager == PackageManager.APK
    finally:
        Path(path).unlink(missing_ok=True)
