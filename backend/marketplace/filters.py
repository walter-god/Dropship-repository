"""django-filter FilterSet definitions for the marketplace app."""

import django_filters
from django_filters import rest_framework as filters

from .models import Application, Category


class ApplicationFilter(filters.FilterSet):
    """
    Allows filtering the Application list by several useful criteria.

    Query parameters
    ----------------
    category        — exact match on Category slug
    category_id     — exact match on Category pk
    is_featured     — boolean (true/false)
    status          — pending | approved | rejected
    min_price       — lower bound (inclusive) on price
    max_price       — upper bound (inclusive) on price
    is_free         — boolean shortcut: price = 0
    developer       — FK pk of the developer user
    tags            — substring match within the tags field
    """

    category = django_filters.CharFilter(
        field_name='category__slug',
        lookup_expr='iexact',
        label='Category slug',
    )
    category_id = django_filters.NumberFilter(
        field_name='category__id',
        label='Category ID',
    )
    is_featured = django_filters.BooleanFilter(
        field_name='is_featured',
        label='Featured only',
    )
    status = django_filters.ChoiceFilter(
        field_name='status',
        choices=Application.STATUS_CHOICES,
        label='Approval status',
    )
    min_price = django_filters.NumberFilter(
        field_name='price',
        lookup_expr='gte',
        label='Minimum price',
    )
    max_price = django_filters.NumberFilter(
        field_name='price',
        lookup_expr='lte',
        label='Maximum price',
    )
    is_free = django_filters.BooleanFilter(
        method='filter_is_free',
        label='Free apps only',
    )
    developer = django_filters.NumberFilter(
        field_name='developer__id',
        label='Developer user ID',
    )
    tags = django_filters.CharFilter(
        field_name='tags',
        lookup_expr='icontains',
        label='Tag substring',
    )
    created_after = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='gte',
        label='Created after (ISO 8601)',
    )
    created_before = django_filters.DateTimeFilter(
        field_name='created_at',
        lookup_expr='lte',
        label='Created before (ISO 8601)',
    )

    class Meta:
        model = Application
        fields = [
            'category', 'category_id', 'is_featured', 'status',
            'min_price', 'max_price', 'is_free', 'developer',
            'tags', 'created_after', 'created_before',
        ]

    def filter_is_free(self, queryset, name, value):
        if value is True:
            return queryset.filter(price=0)
        if value is False:
            return queryset.exclude(price=0)
        return queryset
