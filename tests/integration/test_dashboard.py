"""Tests d'integration des tableaux de bord (recettes et isolation).

Couvre :
1. Le tableau de bord company admin renvoie la recette de la periode demandee.
2. Le tableau de bord super admin agrege toutes les compagnies.
"""
from datetime import datetime

import pytest
from django.utils import timezone

from tests.factories import make_company_admin, make_paid_payment, make_super_admin


def _aware(year, month, day):
    """Return a timezone-aware datetime at midday (avoids TZ edge cases)."""
    return timezone.make_aware(datetime(year, month, day, 12, 0))


# --------------------------------------------------------------------------- #
# 1. Company dashboard — recette sur une plage de dates
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_company_dashboard_revenue_for_date_range(api_client):
    admin, company = make_company_admin(phone="+22670030000")
    # Un paiement dans la plage (juin), un autre en dehors (mai).
    make_paid_payment(company, amount=7000, when=_aware(2026, 6, 15))
    make_paid_payment(company, amount=9999, when=_aware(2026, 5, 1))
    api_client.force_authenticate(user=admin)

    response = api_client.get(
        "/api/v1/company/dashboard/",
        {"period": "custom", "start_date": "2026-06-01", "end_date": "2026-06-30"},
    )

    assert response.status_code == 200
    assert response.data["revenue_total"] == 7000.0


@pytest.mark.django_db
def test_company_dashboard_isolates_other_company_revenue(api_client):
    admin_a, company_a = make_company_admin(phone="+22670031000")
    _, company_b = make_company_admin(phone="+22670031001")
    make_paid_payment(company_a, amount=5000)
    make_paid_payment(company_b, amount=123456)
    api_client.force_authenticate(user=admin_a)

    response = api_client.get("/api/v1/company/dashboard/")

    assert response.status_code == 200
    # L'admin A ne voit jamais la recette de la compagnie B.
    assert response.data["revenue_total"] == 5000.0


# --------------------------------------------------------------------------- #
# 2. Super dashboard — agrege toutes les compagnies
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_super_dashboard_includes_all_companies(api_client):
    _, company_a = make_company_admin(phone="+22670032000")
    _, company_b = make_company_admin(phone="+22670032001")
    make_paid_payment(company_a, amount=5000, commission=500)
    make_paid_payment(company_b, amount=8000, commission=800)
    super_admin = make_super_admin("+22670032002")
    api_client.force_authenticate(user=super_admin)

    overview = api_client.get("/api/v1/super/dashboard/")
    assert overview.status_code == 200
    assert overview.data["total_commission_revenue"] == 1300.0

    by_company = api_client.get("/api/v1/super/dashboard/revenue-by-company/")
    assert by_company.status_code == 200
    revenue_by_name = {row["company"]: row["revenue"] for row in by_company.data}
    assert revenue_by_name.get(company_a.name) == 5000.0
    assert revenue_by_name.get(company_b.name) == 8000.0
