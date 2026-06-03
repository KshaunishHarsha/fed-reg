TARGET_AGENCY_SLUGS = [
    "agricultural-marketing-service",
    "animal-and-plant-health-inspection-service",
    "food-safety-and-inspection-service",
    "food-and-drug-administration",
    "national-oceanic-and-atmospheric-administration",
    "fish-and-wildlife-service",
    "national-institutes-of-health",
]

# Only these document types are fetched. PRESDOCU excluded entirely.
TARGET_DOC_TYPES = ["RULE", "PRORULE", "NOTICE"]

ANCHOR_TERMS = [
    "animal welfare act", "awa", "cites", "cafo",
    "endangered species act", "esa",
    "factory farming", "animal testing", "animal experimentation",
    "concentrated animal feeding operation",
    "migratory bird treaty", "marine mammal protection",
    "fur seal", "animal fighting", "horse protection act",
    "humane slaughter", "humane methods of slaughter",
    "animal enterprise", "great ape", "chimpanzee research",
]

CONTEXT_TERMS = [
    "livestock", "poultry", "cattle", "swine", "equine", "bovine",
    "wildlife", "habitat", "captive", "slaughter", "trapping",
    "hunting", "fur", "aquaculture", "fishery", "marine species",
    "processing facility", "animal feed", "veterinary", "zoological",
    "primate", "rodent", "laboratory animal", "animal by-product",
    "game species", "trophy hunting", "import permit",
]

CONTEXT_THRESHOLD = 2

NOISE_TITLE_KEYWORDS = [
    "airspace", "navigation", "flight path",
    "presidential determination", "advisory committee meeting",
    "agenda", "coast guard", "traffic separation",
    "vessel", "anchorage",
]

AI_MODEL = "gpt-4o-mini"
AI_MAX_TOKENS = 500

PIPELINE_RUN_HOUR = 7
PIPELINE_RUN_MINUTE = 30

FR_API_BASE = "https://www.federalregister.gov/api/v1"
