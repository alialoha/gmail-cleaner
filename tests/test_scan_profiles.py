from gmail_cleaner.policy.models import build_scan_queries, location_filter_query


def test_storage_all_includes_large_and_spam() -> None:
    names = {q.name for q in build_scan_queries("storage", "all")}
    assert "large_attachments" in names
    assert "spam" in names
    assert "trash" in names


def test_storage_promotions_scopes_queries() -> None:
    queries = build_scan_queries("storage", "promotions")
    assert all("category:promotions" in q.q for q in queries)
    assert not any(q.name == "spam" for q in queries)


def test_subscriptions_inbox_breaks_out_tabs() -> None:
    names = {q.name for q in build_scan_queries("subscriptions", "inbox")}
    assert "promotions" in names
    assert "updates" in names
    inbox_queries = build_scan_queries("subscriptions", "inbox")
    assert all("in:inbox" in q.q for q in inbox_queries)


def test_subscriptions_single_tab() -> None:
    queries = build_scan_queries("subscriptions", "promotions")
    assert any(q.name == "promotions_all" for q in queries)
    assert any("older_than:1y" in q.q for q in queries)


def test_location_filter_query() -> None:
    assert location_filter_query("all") == ""
    assert location_filter_query("promotions") == "category:promotions"
    assert location_filter_query("inbox") == "in:inbox"
