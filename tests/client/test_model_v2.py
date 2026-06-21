from datetime import datetime
from dashboard.client.model import (
    ClientData, EmailCampaign, LinkedInCampaign, ReplyRecord, OpenEvent)

def test_new_dataclasses_and_clientdata_fields():
    ec = EmailCampaign(name="Upsta_SFDI_V1", sent=414, opened=140, clicked=42,
                       bounced=41, replied=0)
    lc = LinkedInCampaign(name="Upsta_US_PMP_V1", invites=188, accepted=9,
                          replied=3, variant_message="Hi {{FIRST_NAME}}, I'm ...")
    rr = ReplyRecord(channel="linkedin", campaign="Upsta_US_PMP_V1",
                     sentiment="neutral", name="Donna Saunders", ts=None)
    oe = OpenEvent(channel="email", ts=datetime(2026, 6, 3, 13, 14))
    d = ClientData(email_campaigns=[ec], linkedin_campaigns=[lc],
                   replies=[rr], opens=[oe])
    assert d.email_campaigns[0].clicked == 42
    assert d.linkedin_campaigns[0].variant_message.startswith("Hi")
    assert d.replies[0].sentiment == "neutral"
    assert d.opens[0].ts.hour == 13
    # back-compat defaults
    assert d.emails == [] and d.targets == []
