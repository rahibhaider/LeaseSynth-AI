"""
generation_service.py — The synthetic lease data generation engine.

This module turns a GenerationConfig into a pandas DataFrame of synthetic
commercial lease records. No real tenant names, no real lease agreements,
no real personal information: every identifier is synthetic, and every
row is tagged is_synthetic=True.

Design notes (read this before changing the math):

- A pool of synthetic PROPERTIES is generated first (fewer than the number
  of leases), and each lease is assigned to a property from that pool.
  This mirrors reality: a single building has a size/type/location, and
  multiple leases (tenants over time, or multiple suites) can belong to it.

- occupancy_status is decided FIRST for each lease, and the lease's dates
  (and therefore lease_status) are derived FROM it, rather than the other
  way around. That is what keeps dates/status always internally consistent:
    * "Pending"  -> lease starts in the future
    * "Occupied" -> lease started in the past and is still running today
    * "Vacant"   -> lease ended in the past (tenant has moved out)

- Rent is built from four independently-tunable multipliers (base rate for
  the property type, a location multiplier, a lease-type multiplier, and a
  market-condition multiplier) so that, e.g., NYC office NNN space in a
  high-demand market and a warehouse in a low-demand secondary market both
  land in a believable range. monthly_rent is rounded first, and
  annual_rent / rent_per_sqft are both *derived from that rounded number*,
  so the three figures are always arithmetically consistent to the cent.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta
from faker import Faker

from config import Config

# =====================================================================
# Reference data / business rules
# =====================================================================

PROPERTY_TYPES = ["Office", "Retail", "Industrial", "Warehouse", "Mixed-Use"]

TENANT_INDUSTRIES = [
    "Technology",
    "Healthcare",
    "Retail",
    "Finance",
    "Manufacturing",
    "Logistics",
    "Professional Services",
    "Hospitality",
    "Education",
    "Government",
]

LEASE_TYPES = ["Gross", "Modified Gross", "NNN"]
OCCUPANCY_STATUSES = ["Occupied", "Vacant", "Pending"]
MARKET_CONDITIONS = ["High Demand", "Stable", "Low Demand"]
PAYMENT_FREQUENCIES = ["Monthly", "Annual"]

# City, ST -> rent multiplier relative to a 1.00 "baseline" market.
LOCATION_MULTIPLIERS = {
    "New York, NY": 2.00,
    "San Francisco, CA": 1.85,
    "Los Angeles, CA": 1.55,
    "Boston, MA": 1.40,
    "Washington, DC": 1.35,
    "Seattle, WA": 1.30,
    "Chicago, IL": 1.20,
    "Miami, FL": 1.15,
    "Austin, TX": 1.10,
    "Denver, CO": 1.00,
    "Atlanta, GA": 0.95,
    "Dallas, TX": 0.95,
    "Nashville, TN": 0.90,
    "Phoenix, AZ": 0.90,
    "Charlotte, NC": 0.85,
    "Columbus, OH": 0.75,
    "Indianapolis, IN": 0.70,
    "Kansas City, MO": 0.70,
}

# Annual $ per sqft (low, high), before location/lease-type/market adjustment.
BASE_RENT_PER_SQFT = {
    "Office": (22.0, 55.0),
    "Retail": (18.0, 70.0),
    "Industrial": (4.0, 9.0),
    "Warehouse": (3.0, 7.0),
    "Mixed-Use": (16.0, 45.0),
}

# Typical property size range (sqft) by type.
PROPERTY_SIZE_RANGE = {
    "Office": (1500, 100000),
    "Retail": (900, 25000),
    "Industrial": (10000, 400000),
    "Warehouse": (20000, 750000),
    "Mixed-Use": (5000, 120000),
}

# NNN tenants pay lower base rent but cover more pass-through costs;
# Gross tenants pay a higher, all-in rent. This is what "lease types must
# influence operating expense assumptions" means in practice.
LEASE_TYPE_RENT_MULTIPLIER = {
    "Gross": 1.15,
    "Modified Gross": 1.00,
    "NNN": 0.88,
}

LEASE_TYPE_MAINTENANCE = {
    "Gross": "Landlord",
    "Modified Gross": "Shared",
    "NNN": "Tenant",
}

# (low, high) random multiplier applied on top of the base rate.
MARKET_CONDITION_MULTIPLIER = {
    "High Demand": (1.08, 1.25),
    "Stable": (0.97, 1.05),
    "Low Demand": (0.75, 0.95),
}

OUTPUT_COLUMNS = [
    "lease_id",
    "property_id",
    "tenant_id",
    "property_type",
    "property_location",
    "tenant_industry",
    "property_size_sqft",
    "lease_start_date",
    "lease_end_date",
    "lease_duration_years",
    "payment_frequency",
    "monthly_rent",
    "annual_rent",
    "rent_per_sqft",
    "security_deposit",
    "lease_type",
    "escalation_rate",
    "occupancy_status",
    "renewal_option",
    "maintenance_responsibility",
    "market_condition",
    "lease_status",
    "is_synthetic",
]


# =====================================================================
# Configuration
# =====================================================================

@dataclass
class GenerationConfig:
    num_records: int = 500
    property_types: List[str] = field(default_factory=lambda: list(PROPERTY_TYPES))
    locations: List[str] = field(default_factory=lambda: list(LOCATION_MULTIPLIERS.keys()))
    tenant_industries: List[str] = field(default_factory=lambda: list(TENANT_INDUSTRIES))
    lease_types: List[str] = field(default_factory=lambda: list(LEASE_TYPES))
    occupancy_statuses: List[str] = field(default_factory=lambda: list(OCCUPANCY_STATUSES))
    market_conditions: List[str] = field(default_factory=lambda: list(MARKET_CONDITIONS))
    payment_frequencies: List[str] = field(default_factory=lambda: list(PAYMENT_FREQUENCIES))
    lease_duration_min: int = 1
    lease_duration_max: int = 10
    escalation_rate_min: float = 2.0
    escalation_rate_max: float = 4.0
    scenario_description: str = ""
    seed: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationConfig":
        """Build a validated config from a (JSON) dict, applying defaults
        for anything missing and raising ValueError for anything invalid.
        """
        cfg = cls()

        num_records = data.get("num_records", cfg.num_records)
        try:
            num_records = int(num_records)
        except (TypeError, ValueError):
            raise ValueError("num_records must be an integer")
        if not (Config.MIN_RECORDS <= num_records <= Config.MAX_RECORDS):
            raise ValueError(
                f"num_records must be between {Config.MIN_RECORDS} and {Config.MAX_RECORDS}"
            )
        cfg.num_records = num_records

        def _clean_list(key, allowed, default):
            vals = data.get(key)
            if not vals:
                return list(default)
            if isinstance(vals, str):
                vals = [vals]
            cleaned = [v for v in vals if v in allowed]
            return cleaned or list(default)

        cfg.property_types = _clean_list("property_types", PROPERTY_TYPES, cfg.property_types)
        cfg.tenant_industries = _clean_list(
            "tenant_industries", TENANT_INDUSTRIES, cfg.tenant_industries
        )
        cfg.lease_types = _clean_list("lease_types", LEASE_TYPES, cfg.lease_types)
        cfg.occupancy_statuses = _clean_list(
            "occupancy_statuses", OCCUPANCY_STATUSES, cfg.occupancy_statuses
        )
        cfg.market_conditions = _clean_list(
            "market_conditions", MARKET_CONDITIONS, cfg.market_conditions
        )
        cfg.payment_frequencies = _clean_list(
            "payment_frequencies", PAYMENT_FREQUENCIES, cfg.payment_frequencies
        )

        locations = data.get("locations")
        if locations:
            if isinstance(locations, str):
                locations = [loc.strip() for loc in locations.split(",") if loc.strip()]
            cfg.locations = [str(loc) for loc in locations if str(loc).strip()] or cfg.locations

        try:
            dmin = int(data.get("lease_duration_min", cfg.lease_duration_min))
            dmax = int(data.get("lease_duration_max", cfg.lease_duration_max))
        except (TypeError, ValueError):
            raise ValueError("lease_duration_min/max must be integers")
        if dmin < 1 or dmax < dmin or dmax > 50:
            raise ValueError("lease_duration_min/max must satisfy 1 <= min <= max <= 50")
        cfg.lease_duration_min, cfg.lease_duration_max = dmin, dmax

        try:
            emin = float(data.get("escalation_rate_min", cfg.escalation_rate_min))
            emax = float(data.get("escalation_rate_max", cfg.escalation_rate_max))
        except (TypeError, ValueError):
            raise ValueError("escalation_rate_min/max must be numbers")
        if emin < 0 or emax < emin or emax > 20:
            raise ValueError("escalation_rate_min/max must satisfy 0 <= min <= max <= 20")
        cfg.escalation_rate_min, cfg.escalation_rate_max = emin, emax

        cfg.scenario_description = str(data.get("scenario_description", ""))[:2000]

        seed = data.get("seed")
        cfg.seed = int(seed) if seed not in (None, "") else None

        return cfg

    def to_dict(self) -> dict:
        return asdict(self)


# =====================================================================
# Internal helpers
# =====================================================================

def _generate_dates(occupancy_status: str, duration_years: int, as_of: date, rng: np.random.Generator):
    """Pick lease_start_date / lease_end_date that are consistent with the
    given occupancy_status, relative to `as_of` (the generation run date).
    """
    if occupancy_status == "Pending":
        start = as_of + timedelta(days=int(rng.integers(7, 181)))
        end = start + relativedelta(years=duration_years)
    elif occupancy_status == "Occupied":
        # Start far enough in the past that `as_of` still falls before `end`,
        # with at least a 35-day buffer to absorb leap-year rounding.
        max_offset = max(duration_years * 365 - 35, 1)
        start_offset = int(rng.integers(0, max_offset + 1))
        start = as_of - timedelta(days=start_offset)
        end = start + relativedelta(years=duration_years)
    else:  # "Vacant" -> a lease that has already ended
        end_offset = int(rng.integers(1, 731))  # ended 1 day .. 2 years ago
        end = as_of - timedelta(days=end_offset)
        start = end - relativedelta(years=duration_years)
    return start, end


def _derive_lease_status(start: date, end: date, as_of: date) -> str:
    if start > as_of:
        return "Pending"
    if end < as_of:
        return "Expired"
    return "Active"


def _generate_rent(property_type, location, lease_type, market_condition, size_sqft, rng):
    base_low, base_high = BASE_RENT_PER_SQFT[property_type]
    base_rate = rng.uniform(base_low, base_high)

    loc_mult = LOCATION_MULTIPLIERS.get(location, 1.0)
    lease_mult = LEASE_TYPE_RENT_MULTIPLIER[lease_type]

    mc_low, mc_high = MARKET_CONDITION_MULTIPLIER[market_condition]
    mc_mult = rng.uniform(mc_low, mc_high)

    raw_rent_per_sqft = base_rate * loc_mult * lease_mult * mc_mult
    annual_rent_raw = raw_rent_per_sqft * size_sqft

    # Round monthly first, then derive annual + per-sqft FROM the rounded
    # monthly figure so the three numbers are always exactly consistent.
    monthly_rent = round(float(annual_rent_raw) / 12.0, 2)
    annual_rent = round(monthly_rent * 12.0, 2)
    rent_per_sqft = round(annual_rent / size_sqft, 2)
    return rent_per_sqft, annual_rent, monthly_rent


def _generate_properties(config: GenerationConfig, rng: np.random.Generator, covered_locations: list[str]) -> list:
    """Build a pool of synthetic properties, smaller than the lease count,
    so some properties host more than one lease (turnover / multiple suites).
    """
    avg_leases_per_property = rng.uniform(1.0, 2.5)
    n_properties = max(1, len(covered_locations), round(config.num_records / avg_leases_per_property))

    properties = []
    for p in range(n_properties):
        p_type = str(rng.choice(config.property_types))
        location = covered_locations[p] if p < len(covered_locations) else str(rng.choice(config.locations))
        size_low, size_high = PROPERTY_SIZE_RANGE[p_type]
        size = int(rng.integers(size_low, size_high))
        properties.append(
            {
                "property_id": f"PROP-{p + 1:05d}",
                "property_type": p_type,
                "property_location": location,
                "property_size_sqft": size,
            }
        )
    return properties


# =====================================================================
# Public entry point
# =====================================================================

def generate_lease_dataset(config: GenerationConfig, as_of: Optional[date] = None) -> pd.DataFrame:
    """Generate a synthetic commercial lease dataset per `config`.

    Returns a pandas DataFrame with exactly the columns in OUTPUT_COLUMNS,
    every row internally consistent (dates, rent math, status) by
    construction, and every row tagged is_synthetic=True.
    """
    as_of = as_of or date.today()
    rng = np.random.default_rng(config.seed)

    fake = Faker()
    if config.seed is not None:
        Faker.seed(config.seed)

    n = config.num_records
    covered_locations = list(dict.fromkeys(config.locations))
    if n < len(covered_locations):
        covered_locations = rng.choice(covered_locations, size=n, replace=False).tolist()
    properties = _generate_properties(config, rng, covered_locations)
    n_properties = len(properties)

    records = []
    for i in range(n):
        # Give every covered location a lease before drawing from the full property pool.
        prop = properties[i if i < len(covered_locations) else int(rng.integers(0, n_properties))]

        tenant_industry = str(rng.choice(config.tenant_industries))
        lease_type = str(rng.choice(config.lease_types))
        occupancy_status = str(rng.choice(config.occupancy_statuses))
        market_condition = str(rng.choice(config.market_conditions))
        payment_frequency = str(rng.choice(config.payment_frequencies))
        duration_years = int(rng.integers(config.lease_duration_min, config.lease_duration_max + 1))

        start_dt, end_dt = _generate_dates(occupancy_status, duration_years, as_of, rng)
        lease_status = _derive_lease_status(start_dt, end_dt, as_of)

        rent_per_sqft, annual_rent, monthly_rent = _generate_rent(
            prop["property_type"],
            prop["property_location"],
            lease_type,
            market_condition,
            prop["property_size_sqft"],
            rng,
        )

        escalation_rate = round(float(rng.uniform(config.escalation_rate_min, config.escalation_rate_max)), 2)
        security_deposit = round(monthly_rent * float(rng.uniform(1.0, 3.0)), 2)

        renewal_probability = 0.70 if duration_years >= 5 else 0.55
        renewal_option = "Yes" if rng.random() < renewal_probability else "No"

        tenant_id = f"TEN-{fake.unique.random_number(digits=8, fix_len=True)}"

        records.append(
            {
                "lease_id": f"LS-{i + 1:06d}",
                "property_id": prop["property_id"],
                "tenant_id": tenant_id,
                "property_type": prop["property_type"],
                "property_location": prop["property_location"],
                "tenant_industry": tenant_industry,
                "property_size_sqft": prop["property_size_sqft"],
                "lease_start_date": start_dt.isoformat(),
                "lease_end_date": end_dt.isoformat(),
                "lease_duration_years": duration_years,
                "payment_frequency": payment_frequency,
                "monthly_rent": monthly_rent,
                "annual_rent": annual_rent,
                "rent_per_sqft": rent_per_sqft,
                "security_deposit": security_deposit,
                "lease_type": lease_type,
                "escalation_rate": escalation_rate,
                "occupancy_status": occupancy_status,
                "renewal_option": renewal_option,
                "maintenance_responsibility": LEASE_TYPE_MAINTENANCE[lease_type],
                "market_condition": market_condition,
                "lease_status": lease_status,
                "is_synthetic": True,
            }
        )

    df = pd.DataFrame.from_records(records, columns=OUTPUT_COLUMNS)
    return df
