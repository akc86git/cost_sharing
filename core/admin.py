"""Административный интерфейс Django для всех таблиц сервиса."""
from django.contrib import admin

from .models import Debtor, Event, Person, Purchase


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('id', 'full_name', 'nickname', 'is_admin')
    list_filter = ('is_admin',)
    search_fields = ('full_name', 'nickname')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'description')
    list_filter = ('date',)
    search_fields = ('description',)


class DebtorInline(admin.TabularInline):
    model = Debtor
    extra = 0


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'description', 'event', 'person', 'amount')
    list_filter = ('event',)
    search_fields = ('description',)
    inlines = (DebtorInline,)


@admin.register(Debtor)
class DebtorAdmin(admin.ModelAdmin):
    list_display = ('id', 'purchase', 'person', 'share')
    list_filter = ('purchase__event',)
