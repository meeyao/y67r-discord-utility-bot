from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


class ConversionError(ValueError):
    """Raised when a user requests a conversion we cannot satisfy."""


@dataclass(frozen=True)
class UnitValue:
    unit: str
    label: str
    value: float


@dataclass(frozen=True)
class ConversionResult:
    category: str
    source: UnitValue
    targets: List[UnitValue]
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MeasurementUnit:
    key: str
    category: str
    factor_to_base: float
    label: str
    aliases: Tuple[str, ...] = ()
    default_targets: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TemperatureUnit:
    key: str
    label: str
    aliases: Tuple[str, ...]
    default_targets: Tuple[str, ...]


CATEGORY_LABELS = {
    "length": "Length",
    "weight": "Weight",
    "volume": "Volume",
    "speed": "Speed",
    "area": "Area",
    "temperature": "Temperature",
    "currency": "Currency",
}


CATEGORY_DEFAULT_TARGETS = {
    "length": ("km", "mi"),
    "weight": ("kg", "lb"),
    "volume": ("l", "gal"),
    "speed": ("kph", "mph"),
    "area": ("sqm", "sqft"),
}


class MeasurementConverter:
    def __init__(self) -> None:
        self._units: Dict[str, MeasurementUnit] = {}
        self._aliases: Dict[str, str] = {}
        for category, units in MEASUREMENT_UNITS.items():
            for data in units:
                unit = MeasurementUnit(
                    key=data["key"],
                    category=category,
                    factor_to_base=data["factor"],
                    label=data.get("label", data["key"]),
                    aliases=tuple(data.get("aliases", [])),
                    default_targets=tuple(data.get("targets", [])),
                )
                self._units[unit.key] = unit
                for alias in {unit.key, unit.label, *unit.aliases}:
                    clean = alias.strip().lower()
                    if not clean:
                        continue
                    self._aliases[clean] = unit.key

    def is_unit(self, name: Optional[str]) -> bool:
        if not name:
            return False
        return self._normalize(name) in self._units

    def _normalize(self, name: str) -> Optional[str]:
        if not name:
            return None
        cleaned = name.strip().lower()
        cleaned = cleaned.replace("°", "")
        return self._aliases.get(cleaned)

    def resolve(self, name: str) -> Optional[MeasurementUnit]:
        key = self._normalize(name)
        if not key:
            return None
        return self._units.get(key)

    def convert(
        self, value: float, from_unit: str, to_unit: Optional[str] = None
    ) -> ConversionResult:
        unit_from = self.resolve(from_unit)
        if not unit_from:
            raise ConversionError(f"Unknown unit '{from_unit}'.")

        targets: List[UnitValue] = []
        base_value = value * unit_from.factor_to_base

        if to_unit:
            unit_to = self.resolve(to_unit)
            if not unit_to:
                raise ConversionError(f"Unknown unit '{to_unit}'.")
            if unit_to.category != unit_from.category:
                raise ConversionError("Unit types do not match.")
            converted = base_value / unit_to.factor_to_base
            targets.append(UnitValue(unit=unit_to.key, label=unit_to.label, value=converted))
        else:
            default_targets = self._default_targets(unit_from)
            for key in default_targets:
                if key == unit_from.key:
                    continue
                unit_to = self._units.get(key)
                if not unit_to:
                    continue
                converted = base_value / unit_to.factor_to_base
                targets.append(
                    UnitValue(unit=unit_to.key, label=unit_to.label, value=converted)
                )

            if not targets:
                raise ConversionError("No default targets for this unit.")

        source = UnitValue(unit=unit_from.key, label=unit_from.label, value=value)
        return ConversionResult(category=unit_from.category, source=source, targets=targets)

    def _default_targets(self, unit: MeasurementUnit) -> Sequence[str]:
        if unit.default_targets:
            return unit.default_targets
        return CATEGORY_DEFAULT_TARGETS.get(unit.category, ())

    def supported_units(self) -> Dict[str, List[str]]:
        grouped: Dict[str, List[str]] = {}
        for unit in self._units.values():
            grouped.setdefault(unit.category, []).append(unit.label)
        for labels in grouped.values():
            labels.sort()
        return grouped


class TemperatureConverter:
    def __init__(self) -> None:
        self._units: Dict[str, TemperatureUnit] = {}
        self._aliases: Dict[str, str] = {}
        for data in TEMPERATURE_UNITS:
            unit = TemperatureUnit(
                key=data["key"],
                label=data["label"],
                aliases=tuple(data["aliases"]),
                default_targets=tuple(data["targets"]),
            )
            self._units[unit.key] = unit
            for alias in data["aliases"]:
                self._aliases[alias.lower()] = unit.key

    def is_unit(self, name: Optional[str]) -> bool:
        if not name:
            return False
        return self._normalize(name) in self._units

    def resolve(self, name: str) -> Optional[TemperatureUnit]:
        key = self._normalize(name)
        if not key:
            return None
        return self._units.get(key)

    def _normalize(self, name: str) -> Optional[str]:
        cleaned = name.strip().lower()
        cleaned = cleaned.replace("degrees", "deg")
        cleaned = cleaned.replace("degree", "deg")
        cleaned = cleaned.replace("°", "")
        return self._aliases.get(cleaned)

    def convert(
        self, value: float, from_unit: str, to_unit: Optional[str] = None
    ) -> ConversionResult:
        src = self.resolve(from_unit)
        if not src:
            raise ConversionError(f"Unknown temperature unit '{from_unit}'.")

        targets: List[UnitValue] = []
        goal_units: Sequence[str]
        if to_unit:
            dst = self.resolve(to_unit)
            if not dst:
                raise ConversionError(f"Unknown temperature unit '{to_unit}'.")
            goal_units = (dst.key,)
        else:
            goal_units = src.default_targets

        base_c = self._to_celsius(value, src.key)
        for key in goal_units:
            if key == src.key:
                continue
            dst_unit = self._units[key]
            converted = self._from_celsius(base_c, dst_unit.key)
            targets.append(UnitValue(unit=dst_unit.key, label=dst_unit.label, value=converted))

        if not targets:
            raise ConversionError("No target temperature units supplied.")

        source = UnitValue(unit=src.key, label=src.label, value=value)
        return ConversionResult(category="temperature", source=source, targets=targets)

    @staticmethod
    def _to_celsius(value: float, unit: str) -> float:
        if unit == "c":
            return value
        if unit == "f":
            return (value - 32.0) * (5.0 / 9.0)
        if unit == "k":
            return value - 273.15
        raise ConversionError("Unsupported temperature unit.")

    @staticmethod
    def _from_celsius(value: float, unit: str) -> float:
        if unit == "c":
            return value
        if unit == "f":
            return (value * 9.0 / 5.0) + 32.0
        if unit == "k":
            return value + 273.15
        raise ConversionError("Unsupported temperature unit.")


def format_value(value: float) -> str:
    magnitude = abs(value)
    if magnitude == 0:
        return "0"
    if magnitude >= 1000:
        formatted = f"{value:,.2f}"
    elif magnitude >= 1:
        formatted = f"{value:.2f}"
    else:
        formatted = f"{value:.4f}"
    return formatted.rstrip("0").rstrip(".")


MEASUREMENT_UNITS: Dict[str, List[Dict[str, object]]] = {
    "length": [
        {
            "key": "mm",
            "factor": 0.001,
            "label": "mm",
            "aliases": ["millimeter", "millimeters", "millimetre", "millimetres"],
            "targets": ["in"],
        },
        {
            "key": "cm",
            "factor": 0.01,
            "label": "cm",
            "aliases": ["centimeter", "centimeters", "centimetre", "centimetres"],
            "targets": ["in"],
        },
        {
            "key": "m",
            "factor": 1.0,
            "label": "m",
            "aliases": ["meter", "meters", "metre", "metres"],
            "targets": ["ft", "yd"],
        },
        {
            "key": "km",
            "factor": 1000.0,
            "label": "km",
            "aliases": ["kilometer", "kilometers", "kilometre", "kilometres", "kms"],
            "targets": ["mi"],
        },
        {
            "key": "in",
            "factor": 0.0254,
            "label": "in",
            "aliases": ["inch", "inches"],
            "targets": ["cm"],
        },
        {
            "key": "ft",
            "factor": 0.3048,
            "label": "ft",
            "aliases": ["foot", "feet"],
            "targets": ["m"],
        },
        {
            "key": "yd",
            "factor": 0.9144,
            "label": "yd",
            "aliases": ["yard", "yards"],
            "targets": ["m"],
        },
        {
            "key": "mi",
            "factor": 1609.344,
            "label": "mi",
            "aliases": ["mile", "miles"],
            "targets": ["km"],
        },
        {
            "key": "nmi",
            "factor": 1852.0,
            "label": "nmi",
            "aliases": ["nauticalmile", "nauticalmiles"],
            "targets": ["km"],
        },
    ],
    "weight": [
        {
            "key": "mg",
            "factor": 0.001,
            "label": "mg",
            "aliases": ["milligram", "milligrams"],
            "targets": ["oz"],
        },
        {
            "key": "g",
            "factor": 1.0,
            "label": "g",
            "aliases": ["gram", "grams"],
            "targets": ["oz"],
        },
        {
            "key": "kg",
            "factor": 1000.0,
            "label": "kg",
            "aliases": ["kilogram", "kilograms", "kilo", "kilos"],
            "targets": ["lb"],
        },
        {
            "key": "t",
            "factor": 1_000_000.0,
            "label": "t",
            "aliases": ["tonne", "tonnes", "metricton"],
            "targets": ["lb"],
        },
        {
            "key": "lb",
            "factor": 453.59237,
            "label": "lb",
            "aliases": ["pound", "pounds", "lbs"],
            "targets": ["kg"],
        },
        {
            "key": "oz",
            "factor": 28.349523125,
            "label": "oz",
            "aliases": ["ounce", "ounces"],
            "targets": ["g"],
        },
    ],
    "volume": [
        {
            "key": "ml",
            "factor": 0.001,
            "label": "mL",
            "aliases": ["milliliter", "milliliters", "millilitre", "millilitres"],
            "targets": ["floz"],
        },
        {
            "key": "l",
            "factor": 1.0,
            "label": "L",
            "aliases": ["liter", "liters", "litre", "litres"],
            "targets": ["gal"],
        },
        {
            "key": "floz",
            "factor": 0.0295735,
            "label": "fl oz",
            "aliases": ["floz", "fluidounce", "fluidounces"],
            "targets": ["ml"],
        },
        {
            "key": "cup",
            "factor": 0.236588,
            "label": "cup",
            "aliases": ["cups"],
            "targets": ["ml"],
        },
        {
            "key": "pt",
            "factor": 0.473176,
            "label": "pt",
            "aliases": ["pint", "pints"],
            "targets": ["l"],
        },
        {
            "key": "qt",
            "factor": 0.946353,
            "label": "qt",
            "aliases": ["quart", "quarts"],
            "targets": ["l"],
        },
        {
            "key": "gal",
            "factor": 3.78541,
            "label": "gal",
            "aliases": ["gallon", "gallons"],
            "targets": ["l"],
        },
    ],
    "speed": [
        {
            "key": "mps",
            "factor": 1.0,
            "label": "m/s",
            "aliases": ["mps", "meterpersecond", "metrespersecond"],
            "targets": ["fps"],
        },
        {
            "key": "kph",
            "factor": 1000.0 / 3600.0,
            "label": "km/h",
            "aliases": ["kmh", "kph", "kilometerperhour", "kilometresperhour"],
            "targets": ["mph"],
        },
        {
            "key": "mph",
            "factor": 1609.344 / 3600.0,
            "label": "mph",
            "aliases": ["mileperhour", "milesperhour"],
            "targets": ["kph"],
        },
        {
            "key": "fps",
            "factor": 0.3048,
            "label": "ft/s",
            "aliases": ["footpersecond", "feetpersecond", "fps"],
            "targets": ["mps"],
        },
        {
            "key": "kt",
            "factor": 0.514444,
            "label": "kn",
            "aliases": ["knot", "knots", "kt"],
            "targets": ["kph"],
        },
    ],
    "area": [
        {
            "key": "sqcm",
            "factor": 0.0001,
            "label": "cm²",
            "aliases": ["cm2", "squarecm", "squarecentimeter", "squarecentimetre"],
            "targets": ["sqin"],
        },
        {
            "key": "sqm",
            "factor": 1.0,
            "label": "m²",
            "aliases": ["m2", "squaremeter", "squaremetre"],
            "targets": ["sqft"],
        },
        {
            "key": "sqkm",
            "factor": 1_000_000.0,
            "label": "km²",
            "aliases": ["km2", "squarekilometer", "squarekilometre"],
            "targets": ["sqmi"],
        },
        {
            "key": "sqin",
            "factor": 0.00064516,
            "label": "in²",
            "aliases": ["squareinch", "squareinches", "in2"],
            "targets": ["sqcm"],
        },
        {
            "key": "sqft",
            "factor": 0.09290304,
            "label": "ft²",
            "aliases": ["squarefoot", "squarefeet", "ft2"],
            "targets": ["sqm"],
        },
        {
            "key": "sqyd",
            "factor": 0.836127,
            "label": "yd²",
            "aliases": ["squareyard", "squareyards", "yd2"],
            "targets": ["sqm"],
        },
        {
            "key": "sqmi",
            "factor": 2_589_988.11,
            "label": "mi²",
            "aliases": ["squaremile", "squaremiles", "mi2"],
            "targets": ["sqkm"],
        },
        {
            "key": "acre",
            "factor": 4046.8564224,
            "label": "acre",
            "aliases": ["acres"],
            "targets": ["hectare"],
        },
        {
            "key": "hectare",
            "factor": 10_000.0,
            "label": "hectare",
            "aliases": ["hectares", "ha"],
            "targets": ["acre"],
        },
    ],
}


TEMPERATURE_UNITS: Sequence[Dict[str, object]] = [
    {
        "key": "c",
        "label": "°C",
        "aliases": ["c", "celsius", "centigrade", "degc", "celcius", "°c"],
        "targets": ("f", "k"),
    },
    {
        "key": "f",
        "label": "°F",
        "aliases": ["f", "fahrenheit", "degf", "°f"],
        "targets": ("c", "k"),
    },
    {
        "key": "k",
        "label": "K",
        "aliases": ["k", "kelvin", "°k"],
        "targets": ("c", "f"),
    },
]


__all__ = [
    "CATEGORY_LABELS",
    "ConversionError",
    "ConversionResult",
    "MeasurementConverter",
    "TemperatureConverter",
    "UnitValue",
    "format_value",
]
