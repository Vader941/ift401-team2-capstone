from django import forms

from .services import MAX_QUANTITY


class BuyOrderForm(forms.Form):
    quantity = forms.IntegerField(
        label="Quantity",
        min_value=1,
        max_value=MAX_QUANTITY,
        error_messages={
            "required": "Enter the number of shares to buy.",
            "invalid": "Enter a whole number of shares.",
            "min_value": "Quantity must be at least 1 share.",
            "max_value": "Quantity exceeds the supported limit.",
        },
        widget=forms.NumberInput(
            attrs={"min": "1", "step": "1"}
        ),
    )