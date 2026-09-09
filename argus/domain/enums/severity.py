# -*- coding: utf-8 -*-
"""
domain/enums/severity.py

Canonical severity levels used across the Argus violation model.
"""
from enum import Enum


class Severity(str, Enum):
    CRITICAL = "CRITICAL"   # Fundamental rights violation with material impact
    HIGH = "HIGH"           # Substantial breach of core obligations
    MODERATE = "MODERATE"   # Procedural violation affecting rights
    LOW = "LOW"             # Minor compliance issue
    UNKNOWN = "UNKNOWN"     # Not yet assessed


class LegalStyle(str, Enum):
    CIVIL_LAW = "civil_law"
    COMMON_LAW = "common_law"
    MIXED = "mixed"


class FrameworkType(str, Enum):
    INTERNATIONAL_CONVENTION = "international_convention"
    NATIONAL_LAW = "national_law"
    REGULATION = "regulation"
    CODE = "code"
    ADMINISTRATIVE_RESOLUTION = "administrative_resolution"
    CORPORATE_POLICY = "corporate_policy"
    LEGAL_FRAMEWORK = "legal_framework"


class ActorType(str, Enum):
    ORGANIZATION = "organization"
    INDIVIDUAL = "individual"
    GOVERNMENT = "government"
    SYSTEM = "system"


class RoleType(str, Enum):
    SUSPECT = "suspect"
    VICTIM = "victim"
    WITNESS = "witness"
    RESPONSIBLE = "responsible"
