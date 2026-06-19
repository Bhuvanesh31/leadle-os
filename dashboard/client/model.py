"""Normalized model: the contract every ClientSource returns and compute consumes."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EmailEvent:
    company: str
    to_name: str
    event_type: str
    campaign: str
    ts: datetime
    from_email: str


@dataclass
class LinkedInEvent:
    event_type: str
    company: str
    profile_url: str
    prospect_name: str
    title: str


@dataclass
class WarmLead:
    channel: str
    account: str
    response_date: str
    status: str
    response_text: str
    linkedin_url: str
    name: str
    title: str
    company: str
    company_url: str
    location: str


@dataclass
class TargetCo:
    name: str
    country: str
    location: str
    linkedin_url: str
    industry: str
    size: str
    segment: str
    domain: str
    aimfox_id: str = ""
    aimfox_urn: str = ""
    instantly_id: str = ""


@dataclass
class Context:
    client: str
    channels: list[str] = field(default_factory=list)
    campaign_live_dates: dict = field(default_factory=dict)
    icp: dict = field(default_factory=dict)


@dataclass
class ClientData:
    emails: list[EmailEvent] = field(default_factory=list)
    linkedin: list[LinkedInEvent] = field(default_factory=list)
    warm_leads: list[WarmLead] = field(default_factory=list)
    targets: list[TargetCo] = field(default_factory=list)
    context: Context | None = None
