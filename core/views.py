"""Страницы сайта сервиса «Разделение затрат»."""
from decimal import Decimal, InvalidOperation
from itertools import groupby

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .exports import build_pdf, build_xlsx
from .forms import EventForm, PersonForm, PurchaseForm
from .models import Debtor, Event, Person, Purchase
from .reports import MATRIX_SQL, build_event_report, split_purchase


def index(request):
    """Главная страница: кнопки добавления и ссылка на отчёт."""
    return render(request, 'core/index.html', {
        'people_count': Person.objects.count(),
        'events_count': Event.objects.count(),
        'purchases_count': Purchase.objects.count(),
    })


def person_add(request):
    """Добавление человека (таблица people)."""
    form = PersonForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        person = form.save()
        messages.success(request, f'Человек «{person.full_name}» добавлен.')
        return redirect('index')
    return render(request, 'core/person_add.html', {'form': form})


def event_add(request):
    """Добавление события (таблица events)."""
    form = EventForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        event = form.save()
        messages.success(request, f'Событие «{event.description}» добавлено.')
        return redirect('index')
    return render(request, 'core/event_add.html', {'form': form})


def _parse_debtors(request, people):
    """Разбирает флажки участия и коэффициенты должников из POST-запроса.

    Возвращает (список {'person', 'share', 'raw'}, список текстовых ошибок).
    """
    debtors, errors = [], []
    for person in people:
        if f'debtor_{person.pk}' not in request.POST:
            continue
        raw = (request.POST.get(f'share_{person.pk}') or '1').replace(',', '.').strip()
        try:
            share = Decimal(raw)
        except InvalidOperation:
            errors.append(f'Некорректный коэффициент у «{person.full_name}»: {raw!r}.')
            continue
        if not Decimal('0') < share <= Decimal('1'):
            errors.append(
                f'Коэффициент у «{person.full_name}» должен быть в диапазоне 0 < x <= 1.'
            )
            continue
        debtors.append({'person': person, 'share': share, 'raw': raw})
    if not debtors and not errors:
        errors.append('Отметьте флажками хотя бы одного должника и укажите коэффициенты участия.')
    return debtors, errors


def purchase_add(request):
    """Добавление покупки с разделением по должникам (purchases + debtors)."""
    people = Person.objects.all()
    events = Event.objects.all()
    form = PurchaseForm(request.POST or None)

    debtors, debtor_errors, checked, shares = [], [], set(), {}
    if request.method == 'POST':
        debtors, debtor_errors = _parse_debtors(request, people)
        checked = {d['person'].pk for d in debtors}
        shares = {d['person'].pk: d['raw'] for d in debtors}

        if form.is_valid() and not debtor_errors:
            with transaction.atomic():
                purchase = form.save()
                Debtor.objects.bulk_create(
                    Debtor(purchase=purchase, person=d['person'], share=d['share'])
                    for d in debtors
                )
            messages.success(
                request,
                f'Покупка «{purchase.description}» добавлена, должников: {len(debtors)}.',
            )
            return redirect('index')

    debtor_rows = [
        {'person': p, 'checked': p.pk in checked, 'share': shares.get(p.pk, '1')}
        for p in people
    ]
    return render(request, 'core/purchase_add.html', {
        'form': form,
        'debtor_rows': debtor_rows,
        'debtor_errors': debtor_errors,
        'can_submit': bool(people and events),
    })


def purchases_list(request):
    """Страница «Просмотр покупок»: выбор покупки из списка."""
    purchases = (
        Purchase.objects.select_related('event', 'person')
        .prefetch_related('debtors')
        .order_by('-event__date', 'event_id', 'id')
    )
    groups = [
        {'event': event, 'purchases': list(rows)}
        for event, rows in groupby(purchases, key=lambda p: p.event)
    ]
    return render(request, 'core/purchases.html', {'groups': groups})


def purchase_detail(request, purchase_id):
    """Карточка покупки: кто купил, сумма, кто участвует и с какой долей.

    Коэффициенты участия нормализуются (сумма долей = 1), см.
    core/reports.py::split_purchase.
    """
    purchase = get_object_or_404(
        Purchase.objects.select_related('event', 'person'), pk=purchase_id,
    )
    rows = [
        {
            'person': r['person'],
            'share': float(r['share']),
            'money': float(r['money']),
        }
        for r in split_purchase(purchase)
    ]
    return render(request, 'core/purchase_detail.html', {
        'purchase': purchase,
        'debtors': rows,
        'shares_total': 1.0 if rows else 0.0,   # сумма нормализованных долей всегда 1
        'money_total': float(purchase.amount),  # после корректировки округления суммы сходятся
    })


def report(request):
    """Страница отчёта о должниках в рамках выбранного события."""
    events = Event.objects.all()
    event = None
    report_data = None

    event_id = request.GET.get('event') or ''
    if event_id:
        try:
            event = events.get(pk=int(event_id))
        except (ValueError, Event.DoesNotExist):
            messages.error(request, 'Событие не найдено — выберите его из списка.')
        else:
            report_data = build_event_report(event)

    return render(request, 'core/report.html', {
        'events': events,
        'selected_id': event.pk if event else None,
        'report': report_data,
        'matrix_sql': MATRIX_SQL,
    })


def report_export_xlsx(request, event_id):
    """Выгрузка отчёта о должниках в XLSX."""
    event = get_object_or_404(Event, pk=event_id)
    payload = build_xlsx(build_event_report(event))
    response = HttpResponse(
        payload,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="debts-report-event-{event.pk}.xlsx"'
    return response


def report_export_pdf(request, event_id):
    """Выгрузка отчёта о должниках в PDF."""
    event = get_object_or_404(Event, pk=event_id)
    payload = build_pdf(build_event_report(event))
    response = HttpResponse(payload, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="debts-report-event-{event.pk}.pdf"'
    return response
