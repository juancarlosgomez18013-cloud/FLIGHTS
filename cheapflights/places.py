"""Nombres legibles de aeropuertos: código IATA -> ciudad (y país si es fuera de Colombia).

config.yaml puede sobrescribir o añadir nombres en cada zona; esto es el respaldo
(y la fuente para los orígenes, como Bucaramanga, Bogotá y Medellín).
"""

from __future__ import annotations

CITY_NAMES: dict[str, str] = {
    # Colombia
    "BGA": "Bucaramanga",
    "BOG": "Bogotá",
    "MDE": "Medellín",
    "EOH": "Medellín (Olaya Herrera)",
    "APO": "Apartadó",
    "CTG": "Cartagena",
    "BAQ": "Barranquilla",
    "SMR": "Santa Marta",
    "RCH": "Riohacha",
    "VUP": "Valledupar",
    "MTR": "Montería",
    "ADZ": "San Andrés",
    "PEI": "Pereira",
    "AXM": "Armenia",
    "MZL": "Manizales",
    "CLO": "Cali",
    "UIB": "Quibdó",
    "PPN": "Popayán",
    "PSO": "Pasto",
    "CUC": "Cúcuta",
    "AUC": "Arauca",
    "EYP": "Yopal",
    "VVC": "Villavicencio",
    "IBE": "Ibagué",
    "NVA": "Neiva",
    "FLA": "Florencia",
    "LET": "Leticia",
    # Centroamérica y Caribe
    "PTY": "Ciudad de Panamá",
    "SJO": "San José, Costa Rica",
    "GUA": "Ciudad de Guatemala",
    "SAL": "San Salvador, El Salvador",
    "AUA": "Aruba",
    "CUR": "Curazao",
    "PUJ": "Punta Cana, Rep. Dominicana",
    "SDQ": "Santo Domingo, Rep. Dominicana",
    "SJU": "San Juan, Puerto Rico",
    "HAV": "La Habana, Cuba",
    # Norteamérica
    "MEX": "Ciudad de México",
    "CUN": "Cancún, México",
    "MIA": "Miami, EE. UU.",
    "FLL": "Fort Lauderdale, EE. UU.",
    "MCO": "Orlando, EE. UU.",
    "JFK": "Nueva York, EE. UU.",
    "LAX": "Los Ángeles, EE. UU.",
    "YYZ": "Toronto, Canadá",
    # Suramérica
    "LIM": "Lima, Perú",
    "UIO": "Quito, Ecuador",
    "GYE": "Guayaquil, Ecuador",
    "LPB": "La Paz, Bolivia",
    "CCS": "Caracas, Venezuela",
    "GRU": "São Paulo, Brasil",
    "GIG": "Río de Janeiro, Brasil",
    "SCL": "Santiago de Chile",
    "EZE": "Buenos Aires, Argentina",
    "MVD": "Montevideo, Uruguay",
    "ASU": "Asunción, Paraguay",
    # Europa
    "MAD": "Madrid, España",
    "BCN": "Barcelona, España",
    "LIS": "Lisboa, Portugal",
    "CDG": "París, Francia",
    "AMS": "Ámsterdam, Países Bajos",
    "LHR": "Londres, Reino Unido",
    "FCO": "Roma, Italia",
    "FRA": "Fráncfort, Alemania",
    "IST": "Estambul, Turquía",
}


# País de cada destino internacional (ISO 3166), para mostrar su bandera.
COUNTRY: dict[str, str] = {
    "PTY": "PA", "SJO": "CR", "GUA": "GT", "SAL": "SV",
    "AUA": "AW", "CUR": "CW", "PUJ": "DO", "SDQ": "DO", "SJU": "PR", "HAV": "CU",
    "MEX": "MX", "CUN": "MX",
    "MIA": "US", "FLL": "US", "MCO": "US", "JFK": "US", "LAX": "US", "YYZ": "CA",
    "LIM": "PE", "UIO": "EC", "GYE": "EC", "LPB": "BO", "CCS": "VE",
    "GRU": "BR", "GIG": "BR", "SCL": "CL", "EZE": "AR", "MVD": "UY", "ASU": "PY",
    "MAD": "ES", "BCN": "ES", "LIS": "PT", "CDG": "FR", "AMS": "NL", "LHR": "GB",
    "FCO": "IT", "FRA": "DE", "IST": "TR",
}


def flag(code: str) -> str | None:
    """Bandera del país del aeropuerto (None si es nacional o desconocido)."""
    iso = COUNTRY.get(code)
    if not iso:
        return None
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso)


def short_city(name: str) -> str:
    """'Lima, Perú' -> 'Lima'. Útil donde el espacio es poco."""
    return name.split(",")[0].strip()
