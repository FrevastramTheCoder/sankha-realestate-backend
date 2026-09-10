"""Curated Dar es Salaam place layer used by deterministic GIS tools.

The coordinates in this file are place, campus, or landmark centroids. They
are suitable for discovery and spatial ranking, not for claiming an exact
property address. Unknown queries are handled by the external geocoder in
``app.services.gis`` instead of being guessed here.
"""

from __future__ import annotations

import copy
import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


EARTH_RADIUS_KM = 6371.0088


def _place(
    key: str,
    name: str,
    place_type: str,
    district: str,
    ward: Optional[str],
    lat: float,
    lng: float,
    aliases: Sequence[str] = (),
    neighbors: Sequence[str] = (),
    universities: Sequence[str] = (),
    description: str = "",
) -> Dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "type": place_type,
        "district": district,
        "ward": ward,
        "lat": lat,
        "lng": lng,
        "aliases": list(aliases),
        "neighbors": list(neighbors),
        "universities": list(universities),
        "description": description,
        "rent_hint": "",
    }


# This layer is intentionally data-only. Add a record here when a coordinate
# is verified from a trusted geographic source, not from an LLM response.
_PLACE_ROWS: List[Dict[str, Any]] = [
    _place("udsm", "UDSM", "university", "Ubungo", "Mlimani", -6.7815, 39.2047,
            ("udsm", "u d s m", "university of dar es salaam", "university of dar", "dar university",
            "chuo kikuu cha dar es salaam", "chuo kikuu cha udsm", "chuo cha udsm", "mlimani campus"),
           ("mlimani", "makongo", "kijitonyama", "sinza", "mabibo", "mwenge", "manzese", "goba", "kimara"),
           ("udsm",), "University of Dar es Salaam, Mlimani campus."),
    _place("aru", "ARU", "university", "Kinondoni", "Kinondoni", -6.7833, 39.2175,
           ("aru", "a r u", "ardhi university", "chuo kikuu cha ardhi", "chuo cha ardhi", "ardhi", "ardhi chuo"),
           ("mwenge", "kijitonyama", "sinza", "mikocheni", "mlimani", "makongo"),
           ("aru",), "Ardhi University, Observation Hill."),
    _place("ifm", "IFM", "university", "Ilala", "Kivukoni", -6.8141, 39.2822,
           ("ifm", "i f m", "institute of finance management", "chuo cha ifm", "chuo cha finance", "finance management"),
           ("posta", "kivukoni", "kisutu", "upanga", "kariakoo", "mchafukoge", "gerezani", "jamhuri"),
           ("ifm",), "Institute of Finance Management, city centre campus."),
    _place("muhas", "MUHAS", "university", "Ilala", "Upanga East", -6.8015, 39.2696,
           ("muhas", "m u h a s", "muhimbili university", "muhimbili university of health",
            "chuo cha muhimbili", "muhimbili"),
           ("upanga", "kisutu", "jamhuri", "posta", "kivukoni", "kariakoo", "gerezani"),
           ("muhas",), "Muhimbili University of Health and Allied Sciences."),
    _place("dit", "DIT", "university", "Ilala", "Kivukoni", -6.8174, 39.2803,
           ("dit", "d i t", "dar es salaam institute of technology", "chuo cha dit", "chuo cha teknolojia dar"),
           ("kivukoni", "posta", "kisutu", "kariakoo", "gerezani", "upanga"),
           ("dit",), "Dar es Salaam Institute of Technology."),
    _place("cbe", "CBE", "university", "Ilala", "Mchafukoge", -6.8169, 39.2780,
           ("cbe", "c b e", "college of business education", "chuo cha cbe", "chuo cha elimu ya biashara"),
           ("mchafukoge", "kisutu", "kariakoo", "posta", "gerezani", "upanga"),
           ("cbe",), "College of Business Education."),
    _place("duce", "DUCE", "university", "Temeke", "Chang'ombe", -6.8672, 39.2661,
           ("duce", "d u c e", "dar es salaam university college of education", "chuo cha duce", "chuo cha changombe"),
           ("changombe", "miburani", "keko", "tandika", "kurasini", "mtoni"),
           ("duce",), "Dar es Salaam University College of Education."),
    _place("nit", "NIT", "college", "Ubungo", "Mabibo", -6.8262, 39.2171,
           ("nit", "n i t", "national institute of transport", "chuo cha nit", "taasisi ya usafirishaji"),
           ("mabibo", "sinza", "manzese", "mburahati"), ("nit",), "National Institute of Transport."),
    _place("out", "OUT", "university", "Kinondoni", "Kinondoni", -6.7989, 39.2364,
           ("out", "o u t", "open university of tanzania", "chuo kikuu huria", "open university", "chuo cha out"),
           ("magomeni", "mwananyamala", "kijitonyama", "mwenge"), ("out",), "Open University of Tanzania."),
    _place("hkmu", "HKMU", "university", "Kinondoni", "Kawe", -6.7745, 39.2321,
           ("hkmu", "h k m u", "hubert kairuki memorial university", "chuo kikuu cha kairuki", "chuo cha kairuki"),
           ("kawe", "mwenge", "mikocheni", "kijitonyama"), ("hkmu",), "Hubert Kairuki Memorial University."),
    _place("isw", "ISW", "college", "Temeke", "Kurasini", -6.8408, 39.2864,
           ("isw", "i s w", "institute of social work", "chuo cha social work", "taasisi ya kazi za jamii"),
           ("kurasini", "keko", "mtoni", "changombe"), ("isw",), "Institute of Social Work."),
    _place("dmi", "DMI", "college", "Temeke", "Kurasini", -6.8439, 39.2839,
           ("dmi", "d m i", "dar es salaam maritime institute", "chuo cha bahari", "maritime institute"),
           ("kurasini", "keko", "mtoni", "bandari"), ("dmi",), "Dar es Salaam Maritime Institute."),
    _place("mzumbe_dar", "Mzumbe University Dar es Salaam Campus", "university", "Kinondoni", "Kijitonyama", -6.7847, 39.2294,
           ("mzumbe dar", "mzumbe university dar es salaam", "mzumbe dar es salaam campus", "chuo cha mzumbe dar"),
           ("mwenge", "kijitonyama", "mikocheni", "sinza"), ("mzumbe_dar",), "Mzumbe University Dar es Salaam campus."),

    _place("kivukoni", "Kivukoni", "neighborhood", "Ilala", "Kivukoni", -6.8186, 39.2898,
           ("kivukoni",), ("posta", "kisutu", "upanga", "gerezani", "kariakoo", "mchafukoge"), ("ifm", "dit", "cbe")),
    _place("posta", "Posta", "neighborhood", "Ilala", "Kivukoni", -6.8159, 39.2848,
           ("posta",), ("kivukoni", "kisutu", "upanga", "mchafukoge", "jamhuri", "kariakoo"), ("ifm", "dit", "cbe")),
    _place("kisutu", "Kisutu", "neighborhood", "Ilala", "Kisutu", -6.8146, 39.2765,
           ("kisutu",), ("posta", "mchafukoge", "upanga", "kariakoo", "jamhuri"), ("ifm", "dit", "cbe", "muhas")),
    _place("mchafukoge", "Mchafukoge", "neighborhood", "Ilala", "Mchafukoge", -6.8197, 39.2775,
           (), ("kisutu", "kariakoo", "gerezani", "kivukoni"), ("cbe", "ifm")),
    _place("kariakoo", "Kariakoo", "neighborhood", "Ilala", "Kariakoo", -6.8244, 39.2753,
           ("kariakoo", "kariakoo market"), ("mchafukoge", "kisutu", "gerezani", "mchikichini"), ("ifm", "cbe", "dit")),
    _place("gerezani", "Gerezani", "neighborhood", "Ilala", "Gerezani", -6.8297, 39.2811,
           ("gerezani", "geresani"), ("kariakoo", "mchafukoge", "kivukoni", "kurasini"), ("dit", "cbe")),
    _place("upanga", "Upanga", "neighborhood", "Ilala", "Upanga East", -6.8034, 39.2677,
           ("upanga", "upanga east", "upanga west"), ("kisutu", "jamhuri", "posta", "kivukoni", "muhimbili_hospital", "kariakoo"), ("muhas", "ifm")),
    _place("jamhuri", "Jamhuri", "neighborhood", "Ilala", "Upanga West", -6.8086, 39.2786,
           (), ("upanga", "kisutu", "posta", "kivukoni"), ("muhas", "ifm")),
    _place("mnazi_mmoja", "Mnazi Mmoja", "neighborhood", "Ilala", "Kisutu", -6.8092, 39.2711,
           ("mnazi mmoja",), ("upanga", "kisutu", "jangwani", "kariakoo"), ("ifm", "muhas")),
    _place("ilala_town", "Ilala", "neighborhood", "Ilala", "Ilala", -6.8358, 39.2641,
           ("ilala bara", "ilala"), ("kariakoo", "mchikichini", "buguruni", "tabata", "vingunguti", "gerezani"), ("cbe", "ifm")),
    _place("buguruni", "Buguruni", "neighborhood", "Ilala", "Buguruni", -6.8445, 39.2514,
           (), ("ilala_town", "vingunguti", "kariakoo", "tabata"), ("cbe",)),
    _place("tabata", "Tabata", "neighborhood", "Ilala", "Tabata", -6.8675, 39.2242,
           ("tabata bara",), ("buguruni", "vingunguti", "segerea", "ukonga", "ilala_town"), ("cbe", "ifm")),
    _place("vingunguti", "Vingunguti", "neighborhood", "Ilala", "Vingunguti", -6.8547, 39.2103,
           (), ("buguruni", "tabata", "segerea", "kipawa", "mburahati"), ("cbe",)),
    _place("kipawa", "Kipawa", "neighborhood", "Ilala", "Kipawa", -6.8733, 39.1961,
           (), ("vingunguti", "segerea", "ukonga", "kimara")),
    _place("ukonga", "Ukonga", "neighborhood", "Ilala", "Ukonga", -6.8402, 39.1810,
           ("ukonga mwisho",), ("segerea", "kipawa", "tabata")),

    _place("kinondoni_hood", "Kinondoni", "neighborhood", "Kinondoni", "Kinondoni", -6.7936, 39.2352,
           ("kinondoni shauri moyo", "kinondoni"), ("mwananyamala", "kijitonyama", "mwenge", "mikocheni", "magomeni"), ("out", "hkmu", "udsm")),
    _place("mwananyamala", "Mwananyamala", "neighborhood", "Kinondoni", "Mwananyamala", -6.7956, 39.2422,
           (), ("kinondoni_hood", "ndugumbi", "hananasif", "mikocheni", "magomeni"), ("out", "udsm")),
    _place("ndugumbi", "Ndugumbi", "neighborhood", "Kinondoni", "Ndugumbi", -6.7897, 39.2444,
           (), ("mwananyamala", "kijitonyama", "mikocheni", "kinondoni_hood"), ("out",)),
    _place("makumbusho", "Makumbusho", "neighborhood", "Kinondoni", "Makumbusho", -6.7834, 39.2355,
           ("makumbusho",), ("kijitonyama", "mwenge", "kinondoni_hood", "mwananyamala"), ("aru",)),
    _place("kijitonyama", "Kijitonyama", "neighborhood", "Kinondoni", "Kijitonyama", -6.7903, 39.2250,
           ("kijitonyama",), ("sinza", "mwenge", "mikocheni", "makumbusho", "mlimani"), ("aru", "udsm", "mzumbe_dar")),
    _place("hananasif", "Hananasif", "neighborhood", "Kinondoni", "Hananasif", -6.7952, 39.2548,
           (), ("mwananyamala", "mikocheni", "kinondoni_hood"), ("out",)),
    _place("mikocheni", "Mikocheni", "neighborhood", "Kinondoni", "Mikocheni", -6.7777, 39.2537,
           ("mikocheni", "mikocheni b"), ("msasani", "mwananyamala", "hananasif", "mwenge", "kijitonyama", "masaki"), ("aru", "udsm", "hkmu")),
    _place("msasani", "Msasani", "neighborhood", "Kinondoni", "Msasani", -6.7572, 39.2500,
           (), ("masaki", "mikocheni", "kawe")),
    _place("masaki", "Masaki", "neighborhood", "Kinondoni", "Msasani", -6.7444, 39.2618,
           ("masaki",), ("msasani", "mikocheni")),
    _place("oyster_bay", "Oyster Bay", "neighborhood", "Kinondoni", "Msasani", -6.7417, 39.2666,
           ("oyster bay", "coco beach side"), ("masaki", "msasani", "mikocheni")),
    _place("kawe", "Kawe", "neighborhood", "Kinondoni", "Kawe", -6.7667, 39.2353,
           (), ("mwenge", "kunduchi", "mikocheni"), ("udsm", "aru", "hkmu")),
    _place("mbezi_beach", "Mbezi Beach", "neighborhood", "Kinondoni", "Mbezi Beach", -6.7300, 39.2200,
           ("mbezi beach", "mbezi"), ("kawe", "tegeta", "bunju", "kunduchi"), ("udsm", "aru")),
    _place("kunduchi", "Kunduchi", "neighborhood", "Kinondoni", "Kunduchi", -6.7094, 39.2308,
           ("kunduchi", "kunduchi beach"), ("kawe", "mbweni", "tegeta"), ("udsm", "aru")),
    _place("bunju", "Bunju", "neighborhood", "Kinondoni", "Bunju", -6.6956, 39.1900,
           (), ("tegeta", "mbweni", "wazo"), ("udsm", "aru")),
    _place("tegeta", "Tegeta", "neighborhood", "Kinondoni", "Tegeta", -6.7158, 39.2053,
           ("tegeta",), ("bunju", "wazo"), ("udsm", "aru")),
    _place("magomeni", "Magomeni", "neighborhood", "Kinondoni", "Magomeni", -6.8010, 39.2480,
           ("magomeni", "magomeni mapipa"), ("manzese", "kinondoni_hood", "tandale", "mwananyamala", "sinza"), ("udsm", "ifm", "out")),
    _place("tandale", "Tandale", "neighborhood", "Kinondoni", "Tandale", -6.8064, 39.2239,
           (), ("manzese", "magomeni", "sinza", "mabibo"), ("udsm", "nit")),
    _place("manzese", "Manzese", "neighborhood", "Kinondoni", "Manzese", -6.8199, 39.2128,
           (), ("sinza", "mabibo", "tandale", "magomeni"), ("udsm", "nit")),
    _place("mwenge", "Mwenge", "neighborhood", "Kinondoni", "Kijitonyama", -6.7842, 39.2272,
           ("mwenge", "mwenge area"), ("kijitonyama", "makumbusho", "mikocheni", "kawe"), ("aru", "udsm", "hkmu")),

    _place("ubungo_terminal", "Ubungo", "neighborhood", "Ubungo", "Ubungo", -6.8047, 39.2178,
           ("ubungo", "ubungo terminal", "uda terminal", "ubungo mkwajuni"), ("sinza", "mabibo", "manzese", "kimara", "mlimani"), ("udsm", "nit")),
    _place("sinza", "Sinza", "neighborhood", "Ubungo", "Sinza", -6.8128, 39.2297,
           ("sinza", "sinza mori", "sinza mikoroshini", "sinza keys"), ("kijitonyama", "mabibo", "ubungo_terminal", "manzese", "mwenge", "magomeni"), ("udsm", "aru", "nit")),
    _place("mabibo", "Mabibo", "neighborhood", "Ubungo", "Mabibo", -6.8275, 39.2205,
           (), ("ubungo_terminal", "sinza", "manzese", "mburahati"), ("udsm", "nit")),
    _place("makuburi", "Makuburi", "neighborhood", "Ubungo", "Makuburi", -6.8219, 39.2399,
           (), ("sinza", "mburahati", "mabibo"), ("nit", "udsm")),
    _place("mburahati", "Mburahati", "neighborhood", "Ubungo", "Mburahati", -6.8350, 39.2056,
           (), ("mabibo", "vingunguti", "sinza"), ("nit",)),
    _place("mlimani", "Mlimani", "neighborhood", "Ubungo", "Mlimani", -6.7815, 39.2047,
           ("mlimani", "mlimani city area"), ("udsm", "makongo", "kijitonyama", "goba", "sinza"), ("udsm", "aru")),
    _place("makongo", "Makongo", "neighborhood", "Ubungo", "Goba", -6.7839, 39.1918,
           (), ("mlimani", "goba", "kimara", "kijitonyama"), ("udsm", "aru")),
    _place("goba", "Goba", "neighborhood", "Ubungo", "Goba", -6.7968, 39.1753,
           (), ("mlimani", "makongo", "kimara"), ("udsm", "aru")),
    _place("kimara", "Kimara", "neighborhood", "Ubungo", "Kimara", -6.7919, 39.1547,
           ("kimara", "kimara korogwe"), ("ubungo_terminal", "kibamba", "goba"), ("udsm", "aru")),
    _place("kibamba", "Kibamba", "neighborhood", "Ubungo", "Kibamba", -6.7953, 39.1292,
           (), ("kimara", "kwembe", "chanika"), ("udsm", "aru")),
    _place("mbezi_juu", "Mbezi Juu", "neighborhood", "Ubungo", "Mbezi Juu", -6.7611, 39.1819,
           ("mbezi juu",), ("goba", "kwembe", "kimara"), ("udsm", "aru")),
    _place("mbezi_louis", "Mbezi Luis", "neighborhood", "Ubungo", "Mbezi Louis", -6.7700, 39.1533,
           ("mbezi luis", "mbezi louis", "bezi luis"), ("kimara", "kwembe", "kibamba"), ("udsm", "aru")),

    _place("temeke_town", "Temeke", "neighborhood", "Temeke", "Temeke", -6.8844, 39.2572,
           ("temeke", "temeke town"), ("tandika", "changombe", "keko", "mtoni", "yombo"), ("duce", "dmi", "isw")),
    _place("tandika", "Tandika", "neighborhood", "Temeke", "Tandika", -6.8750, 39.2456,
           (), ("mbagala", "changombe", "temeke_town", "keko", "yombo"), ("duce",)),
    _place("changombe", "Chang'ombe", "neighborhood", "Temeke", "Chang'ombe", -6.8672, 39.2661,
           ("changombe", "chang o mbe", "chango mbe"), ("miburani", "keko", "tandika", "temeke_town", "kurasini"), ("duce",)),
    _place("miburani", "Miburani", "neighborhood", "Temeke", "Miburani", -6.8722, 39.2675,
           (), ("changombe", "keko", "temeke_town"), ("duce",)),
    _place("keko", "Keko", "neighborhood", "Temeke", "Keko", -6.8589, 39.2703,
           ("keko", "keko machungwa"), ("changombe", "miburani", "kurasini", "temeke_town"), ("duce", "dmi")),
    _place("kurasini", "Kurasini", "neighborhood", "Temeke", "Kurasini", -6.8403, 39.2842,
           (), ("keko", "mtoni", "changombe", "gerezani", "bandari"), ("isw", "dmi")),
    _place("mtoni", "Mtoni", "neighborhood", "Temeke", "Mtoni", -6.8794, 39.2947,
           (), ("kurasini", "temeke_town", "mbagala", "kijichi"), ("duce",)),
    _place("mbagala", "Mbagala", "neighborhood", "Temeke", "Mbagala", -6.9111, 39.2736,
           ("mbagala", "mbagala rangi tatu"), ("tandika", "kijichi", "yombo", "chamazi", "charambe"), ("duce",)),
    _place("kijichi", "Kijichi", "neighborhood", "Temeke", "Kijichi", -6.9075, 39.2631,
           (), ("yombo", "mbagala", "mtoni"), ("duce",)),
    _place("kigamboni_town", "Kigamboni", "neighborhood", "Kigamboni", "Kigamboni", -6.8311, 39.3100,
           ("kigamboni", "kigamboni town"), ("vijibweni", "mjimwema", "kibada"), ("duce",)),
    _place("vijibweni", "Vijibweni", "neighborhood", "Kigamboni", "Vijibweni", -6.8411, 39.3078,
           (), ("kigamboni_town", "kibada")),
    _place("mjimwema", "Mjimwema", "neighborhood", "Kigamboni", "Mjimwema", -6.8617, 39.3381,
           (), ("kigamboni_town", "kibada", "vijibweni")),
    _place("kibada", "Kibada", "neighborhood", "Kigamboni", "Kibada", -6.8750, 39.3222,
           (), ("kigamboni_town", "mjimwema", "vijibweni")),

    _place("morogoro_road", "Morogoro Road", "street", "Ubungo", None, -6.8197, 39.2497,
           ("morogoro road", "barabara ya morogoro", "moro road"), ("kariakoo", "ilala_town", "buguruni", "gerezani")),
    _place("bagamoyo_road", "Bagamoyo Road", "street", "Kinondoni", None, -6.7556, 39.2601,
           ("bagamoyo road", "barabara ya bagamoyo", "new bagamoyo road"), ("mikocheni", "kawe", "kunduchi", "msasani", "bunju")),
    _place("ali_hassan_mwinyi", "Ali Hassan Mwinyi Road", "street", "Kinondoni", None, -6.7925, 39.2631,
           ("ali hassan mwinyi road", "ahm road", "unu road"), ("upanga", "mwananyamala", "mikocheni", "kinondoni_hood")),
    _place("kilwa_road", "Kilwa Road", "street", "Temeke", None, -6.8750, 39.2760,
           ("kilwa road", "nelson mandela road", "barabara ya kilwa"), ("kurasini", "temeke_town", "mbagala", "yombo")),
    _place("nyerere_road", "Nyerere Road", "street", "Ilala", None, -6.8515, 39.2425,
           ("nyerere road", "pugu road", "barabara ya pugu"), ("ilala_town", "buguruni", "kipawa", "ukonga")),
    _place("ubungo_bus_terminal", "Ubungo Bus Terminal", "transport", "Ubungo", "Ubungo", -6.8047, 39.2178,
           ("ubungo bus terminal", "uda", "uda terminal", "ubungo bus stand"), ("ubungo_terminal", "sinza", "mabibo")),
    _place("jnia", "Julius Nyerere International Airport", "transport", "Ilala", "Ukonga", -6.8735, 39.2072,
           ("jnia", "julius nyerere international airport", "uwanja wa ndege dar", "airport dar", "terminal three"), ("ukonga", "segerea", "kipawa")),
    _place("bandari", "Dar es Salaam Port", "landmark", "Temeke", None, -6.8318, 39.2873,
           ("bandari", "dar es salaam port", "port of dar", "harbour"), ("gerezani", "kivukoni", "kurasini", "mtoni")),
    _place("kariakoo_market", "Kariakoo Market", "market", "Ilala", None, -6.8220, 39.2748,
           ("kariakoo market", "soko la kariakoo", "soko kuu"), ("kariakoo", "mchafukoge", "mchikichini", "gerezani")),
    _place("muhimbili_hospital", "Muhimbili National Hospital", "hospital", "Ilala", "Upanga East", -6.8017, 39.2694,
           ("muhimbili hospital", "muhimbili national hospital", "hospitali ya muhimbili", "muhimbili"), ("upanga", "muhas", "jamhuri")),
    _place("mikocheni_hospital", "Mikocheni Hospital", "hospital", "Kinondoni", None, -6.7786, 39.2569,
           ("mikocheni hospital", "mission mikocheni hospital", "hospitali ya mikocheni"), ("mikocheni", "hananasif")),
    _place("mlimani_city", "Mlimani City", "landmark", "Ubungo", None, -6.7992, 39.2219,
           ("mlimani city", "mlimani city mall", "city mall"), ("ubungo_terminal", "sinza", "mlimani")),
    _place("slipway", "Slipway", "landmark", "Kinondoni", None, -6.7489, 39.2717,
           ("slipway", "slipway shore"), ("msasani", "masaki")),
    _place("coco_beach", "Coco Beach", "landmark", "Kinondoni", None, -6.7319, 39.2728,
           ("coco beach", "coco", "coco beach kinondoni"), ("masaki", "msasani")),
]


PLACES: Dict[str, Dict[str, Any]] = {item["key"]: item for item in _PLACE_ROWS}


def normalize(text: str) -> str:
    """Normalize Swahili/English place text for safe alias matching."""

    if not text:
        return ""
    value = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    value = value.casefold().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _alias_map() -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for key, place in PLACES.items():
        for value in [place["name"], key, *place.get("aliases", [])]:
            normalized = normalize(value)
            if normalized:
                aliases.setdefault(normalized, key)
    return aliases


ALIAS_INDEX = _alias_map()


def _copy(place: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(place)


def _matching_places(message: str) -> List[Tuple[int, int, Dict[str, Any]]]:
    text = normalize(message)
    if not text:
        return []

    found: Dict[str, Tuple[int, int, Dict[str, Any]]] = {}
    for alias, key in ALIAS_INDEX.items():
        match = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text)
        if match:
            candidate = (match.start(), -len(alias), PLACES[key])
            previous = found.get(key)
            if previous is None or candidate[:2] < previous[:2]:
                found[key] = candidate

    # Handle a single obvious typo such as "mikochenii" without turning any
    # arbitrary word into a geographic fact.
    if not found and len(text.split()) <= 4:
        best: Optional[Tuple[float, Dict[str, Any]]] = None
        for alias, key in ALIAS_INDEX.items():
            if len(alias) < 4 or " " in alias:
                continue
            score = SequenceMatcher(None, text, alias).ratio()
            if score >= 0.86 and (best is None or score > best[0]):
                best = (score, PLACES[key])
        if best:
            found[best[1]["key"]] = (0, -len(normalize(best[1]["name"])), best[1])

    return sorted(found.values(), key=lambda item: (item[0], item[1], item[2]["key"]))


def resolve_places(message: str) -> List[Dict[str, Any]]:
    """Resolve all known place references in a user message."""

    return [_copy(item[2]) for item in _matching_places(message)]


def distance_km(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    lat1, lng1, lat2, lng2 = map(
        math.radians,
        (float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"])),
    )
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, value))))


def places_near(
    anchor: Dict[str, Any],
    radius_km: float = 3.0,
    types: Optional[set] = None,
    exclude: Optional[set] = None,
    limit: int = 12,
) -> List[Tuple[Dict[str, Any], float]]:
    """Return known place centroids within a geodesic radius."""

    results: List[Tuple[Dict[str, Any], float]] = []
    excluded = exclude or set()
    for place in PLACES.values():
        if place["key"] in excluded or (types and place["type"] not in types):
            continue
        distance = distance_km(anchor, place)
        if distance <= radius_km:
            results.append((_copy(place), distance))
    results.sort(key=lambda item: (item[1], item[0]["name"]))
    return results[: max(1, limit)]


def housing_near(
    anchor: Dict[str, Any],
    radius_km: float = 4.0,
    limit: int = 10,
    max_price: Optional[int] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    """Compatibility helper returning no invented housing records.

    Actual accommodation is stored in SQLite and is queried by
    ``accommodation_tools``. This function intentionally never turns a place
    layer rent hint into a property listing.
    """

    return []


def cheap_housing_near(
    anchor: Optional[Dict[str, Any]] = None,
    radius_km: float = 40.0,
    limit: int = 10,
    max_price: Optional[int] = None,
) -> List[Tuple[Dict[str, Any], float]]:
    return []


def find_district(message: str) -> Optional[str]:
    normalized = normalize(message)
    for district in ("Kinondoni", "Ubungo", "Ilala", "Temeke", "Kigamboni"):
        if normalize(district) in normalized:
            return district
    for place in resolve_places(message):
        if place.get("district"):
            return place["district"]
    return None


def places_within_district(district_key: str, types: Optional[set] = None) -> List[Dict[str, Any]]:
    district = normalize(district_key)
    return [
        _copy(place)
        for place in PLACES.values()
        if normalize(place.get("district", "")) == district
        and (not types or place.get("type") in types)
    ]


def get_district_info(district_key: str) -> Dict[str, Any]:
    district = find_district(district_key) or district_key
    places = places_within_district(district)
    return {
        "name": district,
        "places": places,
        "place_count": len(places),
        "source": "curated_place_layer",
    }


def rent_range_min(place: Dict[str, Any]) -> Optional[int]:
    return None


def bearing_deg(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    lat1, lat2 = math.radians(float(a["lat"])), math.radians(float(b["lat"]))
    delta_lng = math.radians(float(b["lng"]) - float(a["lng"]))
    x = math.sin(delta_lng) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def direction_name(degrees: float) -> str:
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((degrees + 22.5) // 45) % 8]


def closest_in_direction(anchor: Dict[str, Any], direction: str, types: Optional[set] = None, limit: int = 8):
    requested = normalize(direction)
    allowed = {"n": (337.5, 22.5), "e": (67.5, 112.5), "s": (157.5, 202.5), "w": (247.5, 292.5)}
    if requested not in allowed:
        return []
    low, high = allowed[requested]
    matches = []
    for place, distance in places_near(anchor, radius_km=100, types=types, limit=len(PLACES)):
        bearing = bearing_deg(anchor, place)
        in_direction = bearing >= low or bearing <= high if low > high else low <= bearing <= high
        if in_direction:
            matches.append((place, distance))
    return sorted(matches, key=lambda item: item[1])[:limit]


def is_between(place: Dict[str, Any], a: Dict[str, Any], b: Dict[str, Any], margin_km: float = 2.0) -> bool:
    return distance_km(a, place) + distance_km(place, b) <= distance_km(a, b) + margin_km


def places_between(a: Dict[str, Any], b: Dict[str, Any], types: Optional[set] = None, limit: int = 10):
    matches = []
    for place in PLACES.values():
        if types and place.get("type") not in types:
            continue
        if is_between(place, a, b):
            matches.append((_copy(place), min(distance_km(a, place), distance_km(place, b))))
    return sorted(matches, key=lambda item: item[1])[:limit]


def swipe_partner(place: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    nearby = places_near(place, radius_km=3, types={"neighborhood"}, exclude={place.get("key")}, limit=1)
    return nearby[0][0] if nearby else None
