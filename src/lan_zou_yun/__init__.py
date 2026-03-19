from importlib.metadata import PackageNotFoundError, version


__all__ = ["__version__", "get_app_version"]

__version__ = "0.1.0"


def get_app_version():
    try:
        return version("lan-zou-yun")
    except PackageNotFoundError:
        return __version__
