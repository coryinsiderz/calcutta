# 2026 FIFA World Cup — all 48 qualified teams
# UEFA (16), AFC (9), CAF (10), CONCACAF (6), CONMEBOL (6), OFC (1)

TEAMS = [
    # UEFA (16)
    {"name": "England",                 "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    {"name": "France",                  "flag": "🇫🇷"},
    {"name": "Germany",                 "flag": "🇩🇪"},
    {"name": "Spain",                   "flag": "🇪🇸"},
    {"name": "Portugal",                "flag": "🇵🇹"},
    {"name": "Netherlands",             "flag": "🇳🇱"},
    {"name": "Belgium",                 "flag": "🇧🇪"},
    {"name": "Croatia",                 "flag": "🇭🇷"},
    {"name": "Norway",                  "flag": "🇳🇴"},
    {"name": "Switzerland",             "flag": "🇨🇭"},
    {"name": "Austria",                 "flag": "🇦🇹"},
    {"name": "Scotland",                "flag": "🏴󠁧󠁢󠁳󠁣󠁴󠁿"},
    {"name": "Bosnia and Herzegovina",  "flag": "🇧🇦"},
    {"name": "Sweden",                  "flag": "🇸🇪"},
    {"name": "Turkey",                  "flag": "🇹🇷"},
    {"name": "Czech Republic",          "flag": "🇨🇿"},
    # AFC (9)
    {"name": "Japan",                   "flag": "🇯🇵"},
    {"name": "South Korea",             "flag": "🇰🇷"},
    {"name": "Iran",                    "flag": "🇮🇷"},
    {"name": "Saudi Arabia",            "flag": "🇸🇦"},
    {"name": "Australia",               "flag": "🇦🇺"},
    {"name": "Iraq",                    "flag": "🇮🇶"},
    {"name": "Uzbekistan",              "flag": "🇺🇿"},
    {"name": "Jordan",                  "flag": "🇯🇴"},
    {"name": "Qatar",                   "flag": "🇶🇦"},
    # CAF (10)
    {"name": "Morocco",                 "flag": "🇲🇦"},
    {"name": "Senegal",                 "flag": "🇸🇳"},
    {"name": "Egypt",                   "flag": "🇪🇬"},
    {"name": "Algeria",                 "flag": "🇩🇿"},
    {"name": "Ghana",                   "flag": "🇬🇭"},
    {"name": "Cape Verde",              "flag": "🇨🇻"},
    {"name": "South Africa",            "flag": "🇿🇦"},
    {"name": "Ivory Coast",             "flag": "🇨🇮"},
    {"name": "DR Congo",                "flag": "🇨🇩"},
    {"name": "Tunisia",                 "flag": "🇹🇳"},
    # CONCACAF (6 — hosts USA, Canada, Mexico included)
    {"name": "United States",           "flag": "🇺🇸"},
    {"name": "Canada",                  "flag": "🇨🇦"},
    {"name": "Mexico",                  "flag": "🇲🇽"},
    {"name": "Panama",                  "flag": "🇵🇦"},
    {"name": "Haiti",                   "flag": "🇭🇹"},
    {"name": "Curaçao",                 "flag": "🇨🇼"},
    # CONMEBOL (6)
    {"name": "Argentina",               "flag": "🇦🇷"},
    {"name": "Brazil",                  "flag": "🇧🇷"},
    {"name": "Colombia",                "flag": "🇨🇴"},
    {"name": "Uruguay",                 "flag": "🇺🇾"},
    {"name": "Ecuador",                 "flag": "🇪🇨"},
    {"name": "Paraguay",                "flag": "🇵🇾"},
    # OFC (1)
    {"name": "New Zealand",             "flag": "🇳🇿"},
]

assert len(TEAMS) == 48, f"Expected 48 teams, got {len(TEAMS)}"
