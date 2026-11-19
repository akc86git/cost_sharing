"""JSON API сервиса «Разделение затрат».

Endpoints:
* POST /api/people/                  — добавление человека (GET — список);
* POST /api/events/                  — добавление события (GET — список);
* POST /api/purchases/               — добавление покупки с разделением
  по должникам (purchases + debtors) (GET — список);
* GET  /api/events/<id>/report/      — итоговый отчёт о должниках события
  (треугольная матрица долгов, построенная SQL-запросом);
* GET  /api/purchases/<id>/          — карточка покупки: кто купил, сумма,
  кто участвует и с какой долей.

Все запросы принимают и возвращают JSON в кодировке UTF-8.
"""
import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import Debtor, Event, Person, Purchase
from .reports import build_event_report, split_purchase


def _error(message, status=400):
    return JsonResponse({'error': message}, status=status)


def _json_body(request):
    """Разбирает тело запроса как JSON-объект; None — если это не так."""
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _decimal(value):
    """Приводит значение к Decimal (запятая допускается вместо точки)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        result = Decimal(str(value))
    elif isinstance(value, str):
        raw = value.strip().replace(',', '.')
        if not raw:
            return None
        try:
            result = Decimal(raw)
        except InvalidOperation:
            return None
    else:
        return None
    return result if result.is_finite() else None


@csrf_exempt
def api_people(request):
    """Добавление человека / список людей."""
    if request.method == 'GET':
        return JsonResponse({'people': [
            {'id': p.pk, 'full_name': p.full_name, 'nickname': p.nickname,
             'is_admin': p.is_admin}
            for p in Person.objects.all()
        ]})

    data = _json_body(request)
    if data is None:
        return _error('Ожидается JSON-объект в теле запроса.')

    full_name = data.get('full_name')
    if not isinstance(full_name, str) or not full_name.strip():
        return _error('Обязательное поле "full_name" (строка с ФИО) отсутствует или пусто.')
    full_name = full_name.strip()
    if len(full_name) > 200:
        return _error('Поле "full_name" длиннее 200 символов.')

    nickname = data.get('nickname')
    if not isinstance(nickname, str) or not nickname.strip():
        nickname = full_name  # никнейм не задан — используем ФИО
    nickname = nickname.strip()
    if len(nickname) > 100:
        return _error('Поле "nickname" длиннее 100 символов.')

    person = Person.objects.create(
        full_name=full_name,
        nickname=nickname,
        is_admin=bool(data.get('is_admin', False)),
    )
    return JsonResponse(
        {'id': person.pk, 'full_name': person.full_name,
         'nickname': person.nickname, 'is_admin': person.is_admin},
        status=201,
    )


@csrf_exempt
def api_events(request):
    """Добавление события / список событий."""
    if request.method == 'GET':
        return JsonResponse({'events': [
            {'id': e.pk, 'date': e.date.isoformat(), 'description': e.description}
            for e in Event.objects.all()
        ]})

    data = _json_body(request)
    if data is None:
        return _error('Ожидается JSON-объект в теле запроса.')

    try:
        event_date = date.fromisoformat(str(data.get('date', '')).strip())
    except ValueError:
        return _error('Поле "date" обязательно, формат ГГГГ-ММ-ДД (например 2026-11-08).')

    description = data.get('description')
    if not isinstance(description, str) or not description.strip():
        return _error('Обязательное поле "description" (краткое описание события) отсутствует или пусто.')
    description = description.strip()
    if len(description) > 200:
        return _error('Поле "description" длиннее 200 символов.')

    event = Event.objects.create(date=event_date, description=description)
    return JsonResponse(
        {'id': event.pk, 'date': event.date.isoformat(), 'description': event.description},
        status=201,
    )


def _purchase_dict(purchase):
    return {
        'id': purchase.pk,
        'event': purchase.event_id,
        'person': purchase.person_id,
        'description': purchase.description,
        'amount': str(purchase.amount),
        'debtors': [
            {'person': d.person_id, 'share': str(d.share)}
            for d in purchase.debtors.all()
        ],
    }


@csrf_exempt
def api_purchases(request):
    """Добавление покупки с разделением по должникам / список покупок."""
    if request.method == 'GET':
        purchases = Purchase.objects.select_related('event', 'person').all()
        return JsonResponse({'purchases': [_purchase_dict(p) for p in purchases]})

    data = _json_body(request)
    if data is None:
        return _error('Ожидается JSON-объект в теле запроса.')

    try:
        event = Event.objects.get(pk=int(data.get('event')))
    except (TypeError, ValueError, Event.DoesNotExist):
        return _error('Поле "event" (ID события) обязательно и должно указывать на существующее событие.')

    try:
        buyer = Person.objects.get(pk=int(data.get('person')))
    except (TypeError, ValueError, Person.DoesNotExist):
        return _error('Поле "person" (ID человека, совершившего покупку) обязательно '
                      'и должно указывать на существующего человека.')

    description = data.get('description')
    if not isinstance(description, str) or not description.strip():
        return _error('Обязательное поле "description" (краткое описание покупки) отсутствует или пусто.')
    description = description.strip()
    if len(description) > 200:
        return _error('Поле "description" длиннее 200 символов.')

    amount = _decimal(data.get('amount'))
    if amount is None or amount <= 0:
        return _error('Поле "amount" (сумма покупки) обязательно и должно быть положительным числом.')
    if -amount.as_tuple().exponent > 2:
        return _error('Поле "amount": не более двух знаков после запятой.')
    if amount > Decimal('9999999999.99'):
        return _error('Поле "amount": слишком большая сумма (максимум 9 999 999 999.99).')

    raw_debtors = data.get('debtors')
    if not isinstance(raw_debtors, list) or not raw_debtors:
        return _error('Поле "debtors" обязательно: непустой список объектов '
                      '{"person": ID, "share": коэффициент}.')

    prepared, seen = [], set()
    for item in raw_debtors:
        if not isinstance(item, dict):
            return _error('Каждый элемент "debtors" — объект {"person": ID, "share": коэффициент}.')
        try:
            debtor = Person.objects.get(pk=int(item.get('person')))
        except (TypeError, ValueError, Person.DoesNotExist):
            return _error('В "debtors" указан несуществующий человек (поле "person").')
        if debtor.pk in seen:
            return _error(f'Человек {debtor.full_name} указан в "debtors" дважды.')
        share = _decimal(item.get('share', 1))
        if share is None or not Decimal('0') < share <= Decimal('1'):
            return _error(f'Коэффициент участника {debtor.full_name} '
                          'должен быть в диапазоне 0 < x <= 1.')
        seen.add(debtor.pk)
        prepared.append((debtor, share))

    with transaction.atomic():
        purchase = Purchase.objects.create(
            event=event, person=buyer, description=description, amount=amount,
        )
        Debtor.objects.bulk_create(
            Debtor(purchase=purchase, person=debtor, share=share)
            for debtor, share in prepared
        )
    return JsonResponse(_purchase_dict(purchase), status=201)


@csrf_exempt
def api_purchase_detail(request, purchase_id):
    """Карточка покупки: кто купил, сумма, кто участвует и с какой долей.

    Коэффициенты нормализуются: share_normalized — доля участника после
    приведения суммы долей покупки к 1, share_amount — сколько это в деньгах.
    """
    purchase = (
        Purchase.objects.select_related('event', 'person')
        .filter(pk=purchase_id).first()
    )
    if purchase is None:
        return _error('Покупка не найдена.', status=404)
    raw_share = {
        d.person_id: d.share
        for d in purchase.debtors.all()
    }
    return JsonResponse({
        'id': purchase.pk,
        'description': purchase.description,
        'amount': str(purchase.amount),
        'event': {
            'id': purchase.event_id,
            'date': purchase.event.date.isoformat(),
            'description': purchase.event.description,
        },
        'buyer': {
            'id': purchase.person_id,
            'full_name': purchase.person.full_name,
            'nickname': purchase.person.nickname,
        },
        'debtors': [
            {
                'person': row['person'].pk,
                'full_name': row['person'].full_name,
                'nickname': row['person'].nickname,
                'share': str(raw_share[row['person'].pk]),
                'share_normalized': str(
                    row['share'].quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
                ),
                'share_amount': str(row['money']),
            }
            for row in split_purchase(purchase)
        ],
    })


@csrf_exempt
def api_event_report(request, event_id):
    """Итоговый отчёт о должниках в рамках события (матрица долгов)."""
    try:
        event = Event.objects.get(pk=event_id)
    except Event.DoesNotExist:
        return _error('Событие не найдено.', status=404)

    report = build_event_report(event)
    return JsonResponse({
        'event': {'id': event.pk, 'date': event.date.isoformat(),
                  'description': event.description},
        'participants': report['participants'],
        'matrix': report['matrix'],
        'totals': report['totals'],
        'legend': ('matrix[i][j] — сколько участник i должен участнику j; '
                   'на главной диагонали нули; выше главной диагонали — долг '
                   '"строка -> столбец"; ниже диагонали — те же значения '
                   'зеркально со знаком минус.'),
    })
