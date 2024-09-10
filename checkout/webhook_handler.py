from django.http import HttpResponse

from .models import Order, OrderLineItem
from products.models import Product

import json
import time
import random


class StripeWH_Handler:
    """Handle Stripe webhooks"""

    def __init__(self, request):
        self.request = request

    def handle_event(self, event):
        """
        Handle a generic/unknown/unexpected webhook event
        """
        return HttpResponse(
            content=f'Unhandled webhook received: {event["type"]}',
            status=200
        )

    def handle_payment_intent_succeeded(self, event):
        """
        Handle the payment_intent.succeeded webhook from Stripe
        """
        intent = event.data.object
        pid = intent.id
        bag = intent.metadata.bag
        save_info = intent.metadata.save_info

        # Ensure charges are present
        charges = intent.charges.data if hasattr(intent, 'charges') and len(intent.charges.data) > 0 else None
        if not charges:
            return HttpResponse(
                content=f'Webhook received: {event["type"]} | ERROR: No charges found in PaymentIntent',
                status=500
            )

        billing_details = charges[0].billing_details
        shipping_details = intent.shipping or {}
        shipping_address = shipping_details.get('address', {})

        # Clean data in the shipping details
        for field, value in shipping_address.items():
            if value == "":
                shipping_address[field] = None

        grand_total = round(charges[0].amount / 100, 2)

        order_exists = False
        attempt = 1
        while attempt <= 5:
            try:
                order = Order.objects.get(
                    full_name__iexact=shipping_details.get('name'),
                    email__iexact=billing_details.email,
                    phone_number__iexact=shipping_details.get('phone'),
                    country__iexact=shipping_address.get('country'),
                    postcode__iexact=shipping_address.get('postal_code'),
                    town_or_city__iexact=shipping_address.get('city'),
                    street_address1__iexact=shipping_address.get('line1'),
                    street_address2__iexact=shipping_address.get('line2'),
                    county__iexact=shipping_address.get('state'),
                    grand_total=grand_total,
                    original_bag=bag,
                    stripe_pid=pid,
                )
                order_exists = True
                break
            except Order.DoesNotExist:
                attempt += 1
                time.sleep((2 ** attempt) + random.random())  # Exponential backoff with jitter

        if order_exists:
            return HttpResponse(
                content=f'Webhook received: {event["type"]} | SUCCESS: Verified order already in database',
                status=200
            )
        else:
            try:
                order = Order.objects.create(
                    full_name=shipping_details.get('name'),
                    email=billing_details.email,
                    phone_number=shipping_details.get('phone'),
                    country=shipping_address.get('country'),
                    postcode=shipping_address.get('postal_code'),
                    town_or_city=shipping_address.get('city'),
                    street_address1=shipping_address.get('line1'),
                    street_address2=shipping_address.get('line2'),
                    county=shipping_address.get('state'),
                    original_bag=bag,
                    stripe_pid=pid,
                )
                for item_id, item_data in json.loads(bag).items():
                    product = Product.objects.get(id=item_id)
                    if isinstance(item_data, int):
                        order_line_item = OrderLineItem(
                            order=order,
                            product=product,
                            quantity=item_data,
                        )
                        order_line_item.save()
                    else:
                        for size, quantity in item_data['items_by_size'].items():
                            order_line_item = OrderLineItem(
                                order=order,
                                product=product,
                                quantity=quantity,
                                product_size=size,
                            )
                            order_line_item.save()
            except Exception as e:
                if order:
                    order.delete()
                return HttpResponse(
                    content=f'Webhook received: {event["type"]} | ERROR: {e}',
                    status=500
                )

        return HttpResponse(
            content=f'Webhook received: {event["type"]} | SUCCESS: Created order in webhook',
            status=200
        )

    def handle_payment_intent_payment_failed(self, event):
        """
        Handle the payment_intent.payment_failed webhook from Stripe
        """
        return HttpResponse(
            content=f'Webhook received: {event["type"]}',
            status=200
        )