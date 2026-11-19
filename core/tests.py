"""Тесты сервиса «Разделение затрат»."""
import json
from datetime import date
from decimal import Decimal
from io import BytesIO

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from core.models import Debtor, Event, Person, Purchase
from core.reports import build_event_report


def make_people_and_event():
    anna = Person.objects.create(full_name='Анна Иванова', nickname='Аня')
    boris = Person.objects.create(full_name='Борис Петров', nickname='Боря')
    vera = Person.objects.create(full_name='Вера Смирнова', nickname='Вера')
    event = Event.objects.create(date=date(2026, 11, 7), description='Дача')
    return anna, boris, vera, event


def make_classic_scenario():
    """П1: Анна купила шашлык на 300 (ели Аня и Боря по 1).
    П2: Боря оплатил такси 90; Аня съела 0.5, Боря 1, Вера 0.5."""
    anna, boris, vera, event = make_people_and_event()
    p1 = Purchase.objects.create(
        event=event, person=anna, description='Шашлык', amount=Decimal('300.00'),
    )
    Debtor.objects.create(purchase=p1, person=anna)
    Debtor.objects.create(purchase=p1, person=boris)
    p2 = Purchase.objects.create(
        event=event, person=boris, description='Такси', amount=Decimal('90.00'),
    )
    Debtor.objects.create(purchase=p2, person=anna, share=Decimal('0.5'))
    Debtor.objects.create(purchase=p2, person=boris)
    Debtor.objects.create(purchase=p2, person=vera, share=Decimal('0.5'))
    return anna, boris, vera, event


class ModelTests(TestCase):
    def test_db_table_names_match_spec(self):
        self.assertEqual(Person._meta.db_table, 'people')
        self.assertEqual(Event._meta.db_table, 'events')
        self.assertEqual(Purchase._meta.db_table, 'purchases')
        self.assertEqual(Debtor._meta.db_table, 'debtors')

    def test_share_validator(self):
        anna, boris, _, event = make_people_and_event()
        purchase = Purchase.objects.create(
            event=event, person=anna, description='П', amount=Decimal('100'),
        )
        for bad in ('0', '-0.25', '1.0001', '2'):
            with self.assertRaises(ValidationError):
                Debtor(person=boris, purchase=purchase, share=Decimal(bad)).full_clean()
        for good in ('0.0001', '0.5', '1'):
            Debtor(person=boris, purchase=purchase, share=Decimal(good)).full_clean()

    def test_db_check_constraint_on_share(self):
        anna, boris, _, event = make_people_and_event()
        purchase = Purchase.objects.create(
            event=event, person=anna, description='П', amount=Decimal('100'),
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Debtor.objects.create(person=boris, purchase=purchase, share=Decimal('1.5'))

    def test_unique_person_per_purchase(self):
        anna, boris, _, event = make_people_and_event()
        purchase = Purchase.objects.create(
            event=event, person=anna, description='П', amount=Decimal('100'),
        )
        Debtor.objects.create(person=boris, purchase=purchase)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Debtor.objects.create(person=boris, purchase=purchase)


class ApiPeopleTests(TestCase):
    def test_create_and_list(self):
        payload = {'full_name': 'Иванов Иван Иванович', 'nickname': 'Иван', 'is_admin': True}
        resp = self.client.post(
            '/api/people/', data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['nickname'], 'Иван')
        self.assertTrue(Person.objects.filter(is_admin=True).exists())

        resp = self.client.get('/api/people/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['people']), 1)

    def test_full_name_required(self):
        resp = self.client.post(
            '/api/people/', data=json.dumps({'nickname': 'x'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Person.objects.count(), 0)

    def test_nickname_defaults_to_full_name(self):
        resp = self.client.post(
            '/api/people/', data=json.dumps({'full_name': 'Сидор Сидоров'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['nickname'], 'Сидор Сидоров')

    def test_invalid_json(self):
        resp = self.client.post(
            '/api/people/', data='not json', content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


class ApiEventsTests(TestCase):
    def test_create_and_list(self):
        payload = {'date': '2026-11-08', 'description': 'Поездка на дачу'}
        resp = self.client.post(
            '/api/events/', data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Event.objects.count(), 1)

        resp = self.client.get('/api/events/')
        self.assertEqual(len(resp.json()['events']), 1)

    def test_bad_date(self):
        resp = self.client.post(
            '/api/events/',
            data=json.dumps({'date': '08.11.2026', 'description': 'x'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_description(self):
        resp = self.client.post(
            '/api/events/', data=json.dumps({'date': '2026-11-08'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


class ApiPurchasesTests(TestCase):
    def setUp(self):
        self.anna, self.boris, self.vera, self.event = make_people_and_event()

    def _payload(self, **overrides):
        payload = {
            'event': self.event.pk,
            'person': self.anna.pk,
            'description': 'Продукты',
            'amount': '1500,50',
            'debtors': [
                {'person': self.anna.pk, 'share': 1},
                {'person': self.boris.pk, 'share': '0.5'},
            ],
        }
        payload.update(overrides)
        return payload

    def test_create_with_debtors(self):
        resp = self.client.post(
            '/api/purchases/', data=json.dumps(self._payload()),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        purchase = Purchase.objects.get()
        self.assertEqual(purchase.amount, Decimal('1500.50'))
        self.assertEqual(purchase.debtors.count(), 2)
        self.assertEqual(purchase.debtors.get(person=self.boris).share, Decimal('0.5'))

    def test_empty_debtors_rejected(self):
        resp = self.client.post(
            '/api/purchases/', data=json.dumps(self._payload(debtors=[])),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Purchase.objects.count(), 0)

    def test_bad_share_rejected(self):
        payload = self._payload(debtors=[{'person': self.boris.pk, 'share': 0}])
        resp = self.client.post(
            '/api/purchases/', data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_person_rejected(self):
        payload = self._payload(debtors=[{'person': 999, 'share': 1}])
        resp = self.client.post(
            '/api/purchases/', data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_event_rejected(self):
        resp = self.client.post(
            '/api/purchases/', data=json.dumps(self._payload(event=999)),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_negative_amount_rejected(self):
        resp = self.client.post(
            '/api/purchases/', data=json.dumps(self._payload(amount='-5')),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_purchases_list(self):
        self.client.post(
            '/api/purchases/', data=json.dumps(self._payload()),
            content_type='application/json',
        )
        resp = self.client.get('/api/purchases/')
        self.assertEqual(len(resp.json()['purchases']), 1)


class ReportTests(TestCase):
    def setUp(self):
        self.anna, self.boris, self.vera, self.event = make_classic_scenario()

    def test_matrix_values(self):
        report = build_event_report(self.event)
        self.assertEqual(
            [p['nickname'] for p in report['participants']], ['Аня', 'Боря', 'Вера'],
        )
        # Шашлык: Боря должен Ане 150. Такси: Аня должна Боре 22.5, Вера — 22.5.
        # После взаимозачёта: Боря должен Ане 127.5, Вера должна Боре 22.5.
        self.assertEqual(report['matrix'], [
            [0.0, -127.5, 0.0],
            [127.5, 0.0, -22.5],
            [0.0, 22.5, 0.0],
        ])
        self.assertEqual(report['totals'], [-127.5, 105.0, 22.5])

    def test_buyer_not_in_debtors_receives_money(self):
        event2 = Event.objects.create(date=date(2026, 11, 9), description='Кино')
        purchase = Purchase.objects.create(
            event=event2, person=self.vera, description='Билеты', amount=Decimal('120.00'),
        )
        Debtor.objects.create(purchase=purchase, person=self.anna)
        report = build_event_report(event2)
        self.assertEqual(
            [p['nickname'] for p in report['participants']], ['Аня', 'Вера'],
        )
        self.assertEqual(report['matrix'][0][1], 120.0)
        self.assertEqual(report['matrix'][1][0], -120.0)

    def test_empty_event(self):
        empty = Event.objects.create(date=date(2026, 11, 1), description='Пусто')
        report = build_event_report(empty)
        self.assertEqual(report['matrix'], [])
        self.assertEqual(report['participants'], [])

    def test_api_report(self):
        resp = self.client.get(f'/api/events/{self.event.pk}/report/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['matrix'][1][0], 127.5)
        self.assertIn('legend', data)

    def test_api_report_404(self):
        resp = self.client.get('/api/events/999/report/')
        self.assertEqual(resp.status_code, 404)


class PageTests(TestCase):
    def setUp(self):
        self.anna, self.boris, self.vera, self.event = make_classic_scenario()

    def test_index(self):
        resp = self.client.get(reverse('index'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Разделение затрат')

    def test_person_add(self):
        resp = self.client.get(reverse('person_add'))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            reverse('person_add'),
            {'full_name': 'Гришин Григорий', 'nickname': 'Гриша'},
        )
        self.assertRedirects(resp, reverse('index'))
        self.assertTrue(Person.objects.filter(nickname='Гриша').exists())

    def test_event_add(self):
        resp = self.client.post(
            reverse('event_add'),
            {'date': '2026-11-09', 'description': 'Совместный ужин'},
        )
        self.assertRedirects(resp, reverse('index'))
        self.assertTrue(Event.objects.filter(description='Совместный ужин').exists())

    def test_purchase_add_page(self):
        resp = self.client.get(reverse('purchase_add'))
        self.assertContains(resp, 'Коэффициент')

    def test_purchase_add_post(self):
        resp = self.client.post(reverse('purchase_add'), {
            'event': self.event.pk, 'person': self.anna.pk,
            'description': 'Мангал', 'amount': '999.99',
            f'debtor_{self.anna.pk}': 'on', f'share_{self.anna.pk}': '1',
            f'debtor_{self.boris.pk}': 'on', f'share_{self.boris.pk}': '0,5',
        })
        self.assertRedirects(resp, reverse('index'))
        purchase = Purchase.objects.get(description='Мангал')
        self.assertEqual(purchase.debtors.count(), 2)
        self.assertEqual(purchase.debtors.get(person=self.boris).share, Decimal('0.5'))

    def test_purchase_add_without_debtors(self):
        resp = self.client.post(reverse('purchase_add'), {
            'event': self.event.pk, 'person': self.anna.pk,
            'description': 'Без должников', 'amount': '100',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'хотя бы одного должника')
        self.assertEqual(Purchase.objects.filter(description='Без должников').count(), 0)

    def test_report_page(self):
        resp = self.client.get(reverse('report'), {'event': self.event.pk})
        self.assertContains(resp, 'Аня')
        self.assertContains(resp, 'Выгрузить XLS')
        self.assertContains(resp, 'Выгрузить PDF')

    def test_report_page_bad_event(self):
        resp = self.client.get(reverse('report'), {'event': 'abc'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'не найдено')

    def test_export_xlsx(self):
        resp = self.client.get(reverse('report_export_xlsx', args=[self.event.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp['Content-Type'].startswith('application/vnd.openxmlformats'))
        wb = load_workbook(BytesIO(resp.content))
        self.assertIn('Отчёт о должниках', wb.active['A1'].value)

    def test_export_pdf(self):
        resp = self.client.get(reverse('report_export_pdf', args=[self.event.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF-'))
        self.assertGreater(len(resp.content), 1000)


class PurchaseViewTests(TestCase):
    """Страницы «Просмотр покупок» и карточка покупки + JSON-эндпоинт."""

    def setUp(self):
        self.anna, self.boris, self.vera, self.event = make_classic_scenario()

    def test_index_has_purchases_button(self):
        resp = self.client.get(reverse('index'))
        self.assertContains(resp, 'Просмотр покупок')
        self.assertContains(resp, reverse('purchases'))

    def test_purchases_page_lists_all(self):
        resp = self.client.get(reverse('purchases'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Просмотр покупок')
        self.assertContains(resp, 'Дача')          # группировка по событию
        self.assertContains(resp, 'Шашлык')
        self.assertContains(resp, 'Такси')
        self.assertContains(resp, 'Анна Иванова')  # кто купил

    def test_purchases_page_empty(self):
        Purchase.objects.all().delete()
        resp = self.client.get(reverse('purchases'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Покупок пока нет')

    def test_purchase_detail(self):
        purchase = Purchase.objects.get(description='Такси')  # 90; доли 0,5 + 1 + 0,5
        resp = self.client.get(reverse('purchase_detail', args=[purchase.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Такси')
        self.assertContains(resp, 'Борис Петров')      # кто купил
        self.assertContains(resp, 'Анна Иванова')      # участники
        self.assertContains(resp, 'Вера Смирнова')
        self.assertContains(resp, 'Нормализованная доля')
        self.assertContains(resp, '0,25')              # 0,5 / (0,5+1+0,5) = 0,25
        self.assertContains(resp, '0,5')               # 1 / 2 = 0,5
        self.assertContains(resp, '22,50')             # 90 × 0,25 — доли Ани и Веры
        self.assertContains(resp, '45,00')             # 90 × 0,5 — доля Бори
        self.assertContains(resp, '90,00')             # сумма покупки = итого

    def test_purchase_detail_normalization_cents(self):
        """Сумма долей = 1, копейки округления добавляются к наибольшей доле."""
        purchase = Purchase.objects.create(
            event=self.event, person=self.anna,
            description='Обед', amount=Decimal('100.00'),
        )
        for person in (self.anna, self.boris, self.vera):
            Debtor.objects.create(purchase=purchase, person=person)  # share = 1
        resp = self.client.get(reverse('purchase_detail', args=[purchase.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '0,3333')   # 1/3 после нормализации
        self.assertContains(resp, '33,34')    # 33,33 + копейка округления (наибольшая доля)
        self.assertContains(resp, '33,33')
        self.assertContains(resp, '100,00')   # итого совпадает с суммой покупки

    def test_purchase_detail_without_debtors(self):
        purchase = Purchase.objects.create(
            event=self.event, person=self.anna,
            description='Без участников', amount=Decimal('50.00'),
        )
        resp = self.client.get(reverse('purchase_detail', args=[purchase.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'пока нет участников')

    def test_purchase_detail_404(self):
        resp = self.client.get(reverse('purchase_detail', args=[999]))
        self.assertEqual(resp.status_code, 404)

    def test_api_purchase_detail(self):
        purchase = Purchase.objects.get(description='Такси')  # 90; доли 0,5 + 1 + 0,5
        resp = self.client.get(f'/api/purchases/{purchase.pk}/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['buyer']['nickname'], 'Боря')
        self.assertEqual(data['amount'], '90.00')
        self.assertEqual(data['event']['description'], 'Дача')
        by_nickname = {d['nickname']: d for d in data['debtors']}
        self.assertEqual(by_nickname['Аня']['share'], '0.5000')
        self.assertEqual(by_nickname['Аня']['share_normalized'], '0.2500')
        self.assertEqual(by_nickname['Аня']['share_amount'], '22.50')
        self.assertEqual(by_nickname['Боря']['share'], '1.0000')
        self.assertEqual(by_nickname['Боря']['share_normalized'], '0.5000')
        self.assertEqual(by_nickname['Боря']['share_amount'], '45.00')
        self.assertEqual(by_nickname['Вера']['share_amount'], '22.50')
        # сумма нормализованных долей = 1, сумма денег = сумме покупки
        total_norm = sum(Decimal(d['share_normalized']) for d in data['debtors'])
        total_money = sum(Decimal(d['share_amount']) for d in data['debtors'])
        self.assertEqual(total_norm, Decimal('1.0000'))
        self.assertEqual(total_money, Decimal('90.00'))

    def test_api_purchase_detail_404(self):
        resp = self.client.get('/api/purchases/999/')
        self.assertEqual(resp.status_code, 404)
