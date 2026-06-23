"""
US stock/sector → Japanese equivalent mapping.
Used by the analysis layer to identify which JP names are likely to move.
"""

# US ticker → list of (JP ticker, company name, reason)
US_TO_JP = {
    # Semiconductors — kept distinct so the AI doesn't always resolve to the same two JP names
    "NVDA": [("8035.T", "Tokyo Electron", "chip equipment — primary link"), ("6857.T", "Advantest", "chip testing — primary link")],
    "AMD":  [("6857.T", "Advantest", "chip testing"), ("285A.T", "Kioxia", "memory/storage demand")],
    "AMAT": [("8035.T", "Tokyo Electron", "direct chip equipment competitor")],
    "ASML": [("8035.T", "Tokyo Electron", "lithography ecosystem")],
    "MU":   [("285A.T", "Kioxia", "direct NAND/DRAM competitor"), ("4063.T", "Shin-Etsu Chemical", "silicon wafers")],
    "INTC": [("4063.T", "Shin-Etsu Chemical", "silicon wafers")],

    # Apple supply chain
    "AAPL": [
        ("6981.T", "Murata Manufacturing", "components supplier"),
        ("6762.T", "TDK", "components supplier"),
        ("6770.T", "Alps Alpine", "components supplier"),
    ],

    # Automotive / EV
    "TSLA": [("7203.T", "Toyota", "EV competition"), ("7267.T", "Honda", "EV competition"), ("6752.T", "Panasonic", "EV batteries")],
    "GM":   [("7203.T", "Toyota", "auto sector"), ("7267.T", "Honda", "auto sector"), ("7201.T", "Nissan", "auto sector")],

    # Aerospace / Defense / Industrials
    "BA":   [("7011.T", "Mitsubishi Heavy", "major Boeing supplier"), ("7012.T", "Kawasaki Heavy", "major Boeing supplier"), ("7013.T", "IHI", "aircraft engine supplier")],
    "RTX":  [("7011.T", "Mitsubishi Heavy", "defense/aerospace"), ("7013.T", "IHI", "jet engine overlap")],
    "HON":  [("6954.T", "Fanuc", "industrial automation"), ("6861.T", "Keyence", "industrial automation/sensors")],
    "CAT":  [("6301.T", "Komatsu", "construction machinery"), ("6326.T", "Kubota", "machinery sector")],
    "DE":   [("6326.T", "Kubota", "agricultural/construction machinery")],

    # Construction / Real estate / Homebuilders
    "HD":   [("1925.T", "Daiwa House", "homebuilder/construction"), ("1928.T", "Sekisui House", "homebuilder")],
    "DHI":  [("1925.T", "Daiwa House", "homebuilder"), ("1928.T", "Sekisui House", "homebuilder")],
    "LEN":  [("1925.T", "Daiwa House", "homebuilder"), ("1928.T", "Sekisui House", "homebuilder")],
    "PLD":  [("8801.T", "Mitsui Fudosan", "real estate/logistics REIT"), ("8802.T", "Mitsubishi Estate", "real estate")],

    # Cables / fiber
    "GLW":  [("5801.T", "Furukawa Electric", "fiber/cable"), ("5803.T", "Fujikura", "fiber/cable")],

    # Big banks / financials
    "JPM":  [("8306.T", "MUFG", "banking sector"), ("8316.T", "SMFG", "banking sector"), ("8411.T", "Mizuho", "banking sector")],
    "GS":   [("8604.T", "Nomura", "broker/investment bank"), ("8601.T", "Daiwa Securities", "broker")],
    "MS":   [("8604.T", "Nomura", "broker/investment bank")],
    "BAC":  [("8306.T", "MUFG", "banking sector"), ("8316.T", "SMFG", "banking sector")],

    # Insurance
    "MET":  [("8766.T", "Tokio Marine", "insurance sector"), ("8725.T", "MS&AD", "insurance sector")],
    "PRU":  [("8750.T", "Dai-ichi Life", "life insurance")],

    # Telecom
    "VZ":   [("9432.T", "NTT", "telecom sector"), ("9433.T", "KDDI", "telecom sector")],

    # Energy
    "XOM":  [("1605.T", "Inpex", "upstream energy"), ("5020.T", "Eneos", "integrated energy")],
    "CVX":  [("1605.T", "Inpex", "upstream energy")],
    "COP":  [("1605.T", "Inpex", "upstream energy")],

    # Pharma / biotech
    "LLY":  [("4568.T", "Daiichi Sankyo", "ADC oncology partnership"), ("4519.T", "Chugai Pharmaceutical", "oncology")],
    "MRK":  [("4502.T", "Takeda", "pharma sector"), ("4523.T", "Eisai", "pharma sector")],
    "PFE":  [("4502.T", "Takeda", "pharma sector"), ("4503.T", "Astellas", "pharma sector")],

    # Retail / consumer
    "AMZN": [("3382.T", "Seven & i Holdings", "retail/convenience"), ("9983.T", "Fast Retailing", "retail sector")],
    "WMT":  [("3382.T", "Seven & i Holdings", "retail sector")],
    "COST": [("9983.T", "Fast Retailing", "retail sector"), ("3382.T", "Seven & i Holdings", "retail sector")],

    # Tech / cloud / streaming / gaming
    "MSFT": [("9984.T", "SoftBank", "tech conglomerate / ARM stake"), ("7974.T", "Nintendo", "gaming/cloud")],
    "META": [("7974.T", "Nintendo", "digital entertainment"), ("9684.T", "Square Enix", "gaming/digital content")],
    "NFLX": [("6758.T", "Sony", "content/streaming overlap")],
    "GOOGL":[("9984.T", "SoftBank", "AI/tech conglomerate"), ("6861.T", "Keyence", "AI/tech sentiment")],

    # Shipping / logistics
    "FDX":  [("9101.T", "Nippon Yusen", "shipping sector"), ("9104.T", "Mitsui OSK", "shipping sector")],
    "UPS":  [("9101.T", "Nippon Yusen", "shipping sector"), ("9064.T", "Yamato Holdings", "domestic logistics")],

    # Steel / materials
    "NUE":  [("5401.T", "Nippon Steel", "steel sector"), ("5411.T", "JFE Holdings", "steel sector")],
}

# US sector ETF → Japanese sector read-through
SECTOR_ETFS = {
    "XLK":  "Technology",
    "XLE":  "Energy",
    "XLF":  "Financials",
    "XLV":  "Healthcare",
    "XLY":  "Consumer Discretionary",
    "XLP":  "Consumer Staples",
    "XLI":  "Industrials",
    "XLB":  "Materials",
    "XLU":  "Utilities",
    "XLRE": "Real Estate",
}

# US indices to watch
US_INDICES = {
    "^GSPC":    "S&P 500",
    "^IXIC":    "Nasdaq",
    "^DJI":     "Dow Jones",
    "^SOX":     "Philadelphia Semiconductor Index (SOX)",
    "^VIX":     "VIX (fear gauge)",
    "^TNX":     "10-Year Treasury Yield",
    "USDJPY=X": "USD/JPY",
    "CL=F":     "Crude Oil (WTI)",
    "GC=F":     "Gold",
    "^N225":    "Nikkei 225",
}

# US stocks that move with the semiconductor sector index
SEMI_US_STOCKS = {"NVDA", "AMD", "MU", "AMAT", "ASML", "INTC"}

# Individual US stocks to track — 34 names across diverse sectors
CORE_US_STOCKS = [
    # Tech / Semis / FAANGs
    "NVDA", "AAPL", "MSFT", "GOOGL", "META", "AMZN", "NFLX", "MU", "AMD", "AMAT", "ASML",
    # Auto / EV
    "TSLA", "GM",
    # Industrials / Aerospace / Machinery
    "BA", "CAT", "HON", "RTX", "DE",
    # Construction / Home
    "HD", "DHI", "LEN",
    # Financials / Insurance
    "JPM", "GS", "BAC", "MET",
    # Telecom
    "VZ",
    # Energy
    "XOM", "COP",
    # Pharma
    "LLY", "MRK",
    # Retail
    "WMT", "COST",
    # Real Estate / Logistics REIT
    "PLD",
    # Materials / Cables
    "GLW",
]

# Japanese stocks — TOPIX Core 30 + additional market-relevant names (41 total)
CORE_JP_STOCKS = {
    # TOPIX Core 30
    "7203.T": "Toyota",
    "6758.T": "Sony",
    "6861.T": "Keyence",
    "8035.T": "Tokyo Electron",
    "9984.T": "SoftBank Group",
    "9983.T": "Fast Retailing",
    "8306.T": "MUFG",
    "8316.T": "SMFG",
    "8411.T": "Mizuho",
    "4063.T": "Shin-Etsu Chemical",
    "6098.T": "Recruit Holdings",
    "6954.T": "Fanuc",
    "7267.T": "Honda",
    "6902.T": "Denso",
    "9433.T": "KDDI",
    "9432.T": "NTT",
    "8766.T": "Tokio Marine",
    "4568.T": "Daiichi Sankyo",
    "8058.T": "Mitsubishi Corp",
    "6301.T": "Komatsu",
    "6981.T": "Murata",
    "4519.T": "Chugai Pharmaceutical",
    "7974.T": "Nintendo",
    "4661.T": "Oriental Land",
    "1605.T": "Inpex",
    "8591.T": "Orix",
    "6367.T": "Daikin",
    "6857.T": "Advantest",
    "5020.T": "Eneos",
    "8604.T": "Nomura",
    # Aerospace / Defense / Industrials
    "7011.T": "Mitsubishi Heavy",
    "7012.T": "Kawasaki Heavy",
    "7013.T": "IHI",
    # Technology / Memory
    "285A.T": "Kioxia",
    # Infrastructure / Cables
    "5801.T": "Furukawa Electric",
    "5803.T": "Fujikura",
    # Real estate
    "8801.T": "Mitsui Fudosan",
    "8802.T": "Mitsubishi Estate",
    # Construction / Homebuilders
    "1925.T": "Daiwa House",
    "1928.T": "Sekisui House",
    # Machinery / Agriculture
    "6326.T": "Kubota",
}
