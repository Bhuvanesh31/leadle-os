from datetime import datetime, timezone
from dashboard.client.model import (
    EmailEvent, LinkedInEvent, WarmLead, TargetCo, Context, ClientData,
)


def test_clientdata_holds_normalized_records():
    e = EmailEvent("Acme", "Jane", "email_opened", "Upsta_SFDI_V1",
                   datetime(2026, 6, 4, 13, 0, tzinfo=timezone.utc), "augustine@upsta.co")
    li = LinkedInEvent("accepted", "Acme", "https://li/x", "Jane Roe", "CFO")
    wl = WarmLead("LinkedIn", "Rajesh", "5/15/2026", "Long follow up", "Hi...",
                  "https://li/x", "Jane Roe", "CFO", "Acme", "https://acme", "TX")
    tc = TargetCo("Acme", "United States", "TX", "https://li/acme", "Mfg", "501-1,000",
                  "US_Set 1", "acme.com")
    ctx = Context("UPSTA", ["LinkedIn", "Email"], {"Email": "2026-06-03"}, {"seg": "x"})
    data = ClientData([e], [li], [wl], [tc], ctx)
    assert data.emails[0].campaign == "Upsta_SFDI_V1"
    assert data.context.client == "UPSTA"
    assert data.linkedin[0].event_type == "accepted"
