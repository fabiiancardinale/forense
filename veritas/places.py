"""Lugares de Chile mencionados en textos libres (chats, relatos): "voy saliendo de Viña".

Solo cuenta un lugar cuando va junto a una expresión de presencia o movimiento ("estoy en",
"saliendo de", "llegando a", "ando por", "aquí en"...), para no confundir "Santiago" el
nombre con Santiago la ciudad. Las coordenadas son del centro de cada ciudad o comuna:
sirven para distancias entre ciudades, no dentro de una misma comuna.
"""
from __future__ import annotations

import re
import unicodedata

# nombre: (nombre para mostrar, lat, lon)
PLACES = {
    "arica": ("Arica", -18.478, -70.312), "iquique": ("Iquique", -20.214, -70.152), "calama": ("Calama", -22.456, -68.924),
    "antofagasta": ("Antofagasta", -23.650, -70.400), "copiapo": ("Copiapó", -27.366, -70.332),
    "la serena": ("La Serena", -29.904, -71.249), "coquimbo": ("Coquimbo", -29.953, -71.343), "ovalle": ("Ovalle", -30.602, -71.200),
    "los vilos": ("Los Vilos", -31.911, -71.510), "la ligua": ("La Ligua", -32.452, -71.231),
    "vina del mar": ("Viña del Mar", -33.024, -71.552), "vina": ("Viña del Mar", -33.024, -71.552),
    "valparaiso": ("Valparaíso", -33.047, -71.613), "valpo": ("Valparaíso", -33.047, -71.613),
    "quilpue": ("Quilpué", -33.048, -71.442), "villa alemana": ("Villa Alemana", -33.042, -71.373),
    "con con": ("Concón", -32.923, -71.519), "concon": ("Concón", -32.923, -71.519), "renaca": ("Reñaca", -32.978, -71.541),
    "quillota": ("Quillota", -32.881, -71.249), "san felipe": ("San Felipe", -32.750, -70.725), "los andes": ("Los Andes", -32.834, -70.598),
    "casablanca": ("Casablanca", -33.320, -71.410), "algarrobo": ("Algarrobo", -33.363, -71.672),
    "san antonio": ("San Antonio", -33.594, -71.613), "cartagena": ("Cartagena", -33.553, -71.606),
    "santiago": ("Santiago", -33.448, -70.669), "providencia": ("Providencia", -33.426, -70.617),
    "las condes": ("Las Condes", -33.412, -70.570), "vitacura": ("Vitacura", -33.390, -70.570), "nunoa": ("Ñuñoa", -33.456, -70.598),
    "la florida": ("La Florida", -33.522, -70.598), "maipu": ("Maipú", -33.511, -70.757), "puente alto": ("Puente Alto", -33.611, -70.575),
    "la reina": ("La Reina", -33.445, -70.537), "penalolen": ("Peñalolén", -33.486, -70.546), "quilicura": ("Quilicura", -33.366, -70.737),
    "pudahuel": ("Pudahuel", -33.441, -70.759), "san bernardo": ("San Bernardo", -33.592, -70.700), "colina": ("Colina", -33.201, -70.675),
    "lampa": ("Lampa", -33.286, -70.875), "buin": ("Buin", -33.733, -70.743), "talagante": ("Talagante", -33.665, -70.928),
    "melipilla": ("Melipilla", -33.689, -71.215), "farellones": ("Farellones", -33.355, -70.315),
    "rancagua": ("Rancagua", -34.170, -70.741), "machali": ("Machalí", -34.181, -70.649), "san fernando": ("San Fernando", -34.585, -70.989),
    "pichilemu": ("Pichilemu", -34.387, -72.003), "santa cruz": ("Santa Cruz", -34.639, -71.366), "curico": ("Curicó", -34.983, -71.239),
    "talca": ("Talca", -35.426, -71.655), "linares": ("Linares", -35.847, -71.593), "constitucion": ("Constitución", -35.333, -72.412),
    "chillan": ("Chillán", -36.607, -72.103), "concepcion": ("Concepción", -36.827, -73.050), "talcahuano": ("Talcahuano", -36.725, -73.117),
    "los angeles": ("Los Ángeles", -37.469, -72.354), "temuco": ("Temuco", -38.739, -72.598), "pucon": ("Pucón", -39.272, -71.977),
    "villarrica": ("Villarrica", -39.285, -72.228), "valdivia": ("Valdivia", -39.814, -73.246), "osorno": ("Osorno", -40.574, -73.133),
    "puerto varas": ("Puerto Varas", -41.319, -72.985), "puerto montt": ("Puerto Montt", -41.469, -72.942),
    "castro": ("Castro", -42.482, -73.765), "coyhaique": ("Coyhaique", -45.571, -72.068), "punta arenas": ("Punta Arenas", -53.163, -70.917),
    "mendoza": ("Mendoza (Argentina)", -32.889, -68.845),
}
PRESENCE = (r"(?:estoy|estamos|estoi|ando|andamos|voy|vamos|vengo|venimos|sigo|seguimos|saliendo|salgo|salimos|sali|salí|"
            r"llegando|llegue|llegué|llego|llegamos|aqui|aquí|aca|acá|ya|recien|recién|todavia|todavía|aun|aún|quede|quedé|"
            r"quedamos|me fui|nos fuimos|pasando|pasamos|camino|rumbo)")
PREP = r"(?:\s+(?:en|de|desde|a|al|para|por|hacia|pa|po))?"


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


_NAMES = sorted(PLACES, key=len, reverse=True)
_RX = re.compile(rf"\b{PRESENCE}{PREP}(?:\s+\w+){{0,2}}?\s+(?:a\s+|en\s+|de\s+|la\s+)?({'|'.join(re.escape(n) for n in _NAMES)})\b")


def mention(text: str) -> tuple[str, float, float, str] | None:
    """(lugar, lat, lon, frase) si el texto dice dónde está o hacia/desde dónde se mueve quien escribe."""
    plain = _plain(text or "")
    m = _RX.search(plain)
    if not m:
        return None
    name, lat, lon = PLACES[m.group(1)]
    phrase = m.group(0).strip()
    # "voy a Viña" / "llegando a Viña" = destino: la persona aún no está allí
    if re.search(r"\b(voy|vamos|llegando|llego|camino|rumbo|para|pa|hacia)\b", phrase) and not re.search(r"\b(saliendo|salgo|sali|desde|de)\b", phrase):
        return name, lat, lon, "rumbo a"
    return name, lat, lon, "en"
