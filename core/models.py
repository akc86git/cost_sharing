"""Модели сервиса «Разделение затрат».

Схема БД состоит из четырёх таблиц (имена заданы через Meta.db_table):

* people    — сведения о людях;
* events    — сведения о событиях;
* purchases — покупки, привязанные к событиям;
* debtors   — участие людей в потреблении каждой покупки.

Связи:
* у одного события много покупок, каждая покупка относится ровно к одному
  событию (ForeignKey purchases.event) и оплачена ровно одним человеком
  (ForeignKey purchases.person);
* каждая запись debtors связывает одного человека с одной покупкой и
  хранит коэффициент участия (0 < x <= 1, по умолчанию 1).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


def validate_share(value):
    """Коэффициент участия должен лежать в диапазоне 0 < x <= 1."""
    if not (Decimal('0') < Decimal(value) <= Decimal('1')):
        raise ValidationError(
            'Коэффициент участия должен быть больше 0 и не больше 1 (получено %(value)s).',
            params={'value': value},
            code='invalid_share',
        )


class Person(models.Model):
    """Таблица people: сведения о людях."""

    full_name = models.CharField('ФИО (в свободной форме)', max_length=200)
    nickname = models.CharField('Краткий никнейм / прозвище', max_length=100)
    is_admin = models.BooleanField('Администратор сайта', default=False)

    class Meta:
        db_table = 'people'
        ordering = ('full_name', 'id')
        verbose_name = 'человек'
        verbose_name_plural = 'люди'

    def __str__(self):
        return f'{self.full_name} ({self.nickname})'


class Event(models.Model):
    """Таблица events: сведения о событиях."""

    date = models.DateField('Дата события')
    description = models.CharField('Краткое описание события', max_length=200)

    class Meta:
        db_table = 'events'
        ordering = ('-date', 'id')
        verbose_name = 'событие'
        verbose_name_plural = 'события'

    def __str__(self):
        return f'{self.description} от {self.date:%d.%m.%Y}'


class Purchase(models.Model):
    """Таблица purchases: покупки в рамках событий.

    Поле amount (сумма покупки) добавлено к обязательному минимуму полей:
    без суммы отчёт «кто-кому-сколько» невозможно посчитать в деньгах.
    """

    description = models.CharField('Краткое описание покупки', max_length=200)
    event = models.ForeignKey(
        Event, models.CASCADE, related_name='purchases', verbose_name='Событие',
    )
    person = models.ForeignKey(
        Person, models.PROTECT, related_name='purchases',
        verbose_name='Кто совершил покупку',
    )
    amount = models.DecimalField(
        'Сумма покупки, руб.', max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )

    class Meta:
        db_table = 'purchases'
        ordering = ('event', 'id')
        verbose_name = 'покупка'
        verbose_name_plural = 'покупки'

    def __str__(self):
        return f'{self.description} ({self.amount} руб.)'


class Debtor(models.Model):
    """Таблица debtors: участие людей в потреблении позиций из purchases.

    share — коэффициент участия (0 < x <= 1, по умолчанию 1): человек
    потребил покупку полностью (как все) или частично (например, половину
    порции шашлыка — и платит вдвое меньше тех, кто съел полную порцию).
    """

    person = models.ForeignKey(
        Person, models.PROTECT, related_name='debtor_records', verbose_name='Человек',
    )
    purchase = models.ForeignKey(
        Purchase, models.CASCADE, related_name='debtors', verbose_name='Покупка',
    )
    share = models.DecimalField(
        'Коэффициент участия (0 < x <= 1)', max_digits=5, decimal_places=4,
        default=Decimal('1'), validators=[validate_share],
    )

    class Meta:
        db_table = 'debtors'
        ordering = ('id',)
        verbose_name = 'должник'
        verbose_name_plural = 'должники'
        constraints = [
            models.CheckConstraint(
                condition=Q(share__gt=0) & Q(share__lte=1),
                name='debtors_share_range',
            ),
            models.UniqueConstraint(
                fields=('person', 'purchase'),
                name='debtors_unique_person_per_purchase',
            ),
        ]

    def __str__(self):
        return f'{self.person.nickname} — {self.purchase.description} ({self.share})'
