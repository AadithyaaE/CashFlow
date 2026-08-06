"""Shared invoice scoring helpers.

Moved out of main.py (verbatim, no behavior change) so both main.py's routes
and cfo.py's calculations can import the same functions without a circular
import between the two.
"""

from datetime import datetime


def priority_score(invoice):

        try:

            transaction_bonus = 0

            if invoice.transaction_type == "receivable":

                transaction_bonus = 15

            due_date = datetime.strptime(
                invoice.due_date,
                "%d-%m-%Y"
            )

            days_left = (
                due_date -
                datetime.today()
            ).days

            if days_left <= 0:

                due_score = 50

            elif days_left <= 3:

                due_score = 45

            elif days_left <= 7:

                due_score = 35

            elif days_left <= 15:

                due_score = 20

            else:

                due_score = 10

        except:

            due_score = 10

        amount_score = min(
            invoice.amount / 1000,
            30
        )

        category = (
            invoice.category or ""
        ).lower()

        if "rent" in category:

            category_score = 20

        elif "salary" in category:

            category_score = 20

        elif (
            "utility" in category or
            "utilities" in category
        ):

            category_score = 15

        else:

            category_score = 5

        score = (

    (due_score / 50) * 0.50 +

    (amount_score / 30) * 0.30 +

    (category_score / 20) * 0.20

) * 100

        score += transaction_bonus

        return min(
            round(score),
            100
        )


def is_valid_due_date(value):
    # Mirrors the "%d-%m-%Y" format every other part of this file expects
    # (priority_score, /dashboard, etc.) so invoices created here don't
    # silently fail to score/sort/alert correctly later.
    try:
        datetime.strptime(value, "%d-%m-%Y")
        return True
    except (TypeError, ValueError):
        return False
