"""A tiny stand-in for PySide6 used ONLY to smoke-test GUI modules where Qt is
not installed (import errors, NameErrors, bad attribute access in our own code).
It is not a Qt emulator: nothing is rendered. Real Qt testing: tests/gui_smoke.py
with the real PySide6 (QT_QPA_PLATFORM=offscreen)."""
import sys
import types


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Any()

    def __or__(cls, other):
        return Any()


class Any(metaclass=_Meta):
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Any()

    def __call__(self, *a, **k):
        return Any()

    def __iter__(self):
        return iter(())

    def count(self, *a):
        return 0

    def rowCount(self, *a):
        return 0

    def __or__(self, o):
        return self

    __ror__ = __or__

    def __bool__(self):
        return True

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __float__(self):
        return 0.0

    def __lt__(self, o):
        return False

    def __gt__(self, o):
        return False

    def __le__(self, o):
        return True

    def __ge__(self, o):
        return True

    def __truediv__(self, o):
        return 0.0

    __rtruediv__ = __mul__ = __rmul__ = __add__ = __radd__ = __sub__ = __rsub__ = __truediv__


class Signal(Any):
    def __init__(self, *a, **k):
        self._slots = []

    def __get__(self, obj, owner=None):
        return self

    def connect(self, slot, *a, **k):
        self._slots.append(slot)

    def emit(self, *a):
        for s in list(self._slots):
            s(*a)


def Slot(*a, **k):
    return lambda f: f


class _Module(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name == "Signal":
            return Signal
        if name == "Slot":
            return Slot
        cls = _Meta(name, (Any,), {})
        setattr(self, name, cls)
        return cls


def install():
    root = _Module("PySide6")
    root.__path__ = []
    sys.modules["PySide6"] = root
    for sub in ("QtCore", "QtGui", "QtWidgets", "QtSvg", "QtNetwork"):
        m = _Module("PySide6." + sub)
        sys.modules["PySide6." + sub] = m
        setattr(root, sub, m)
