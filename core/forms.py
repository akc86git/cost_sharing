"""Формы страниц сервиса «Разделение затрат»."""
from django import forms

from .models import Event, Person, Purchase


class StyledFormMixin:
    """Добавляет CSS-классы полям формы в зависимости от типа виджета."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css = 'checkbox'
            elif isinstance(field.widget, forms.Select):
                css = 'form-select'
            else:
                css = 'form-input'
            existing = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = f'{existing} {css}'.strip()


class PersonForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Person
        fields = ('full_name', 'nickname', 'is_admin')
        widgets = {
            'full_name': forms.TextInput(attrs={'placeholder': 'Иванов Иван Иванович'}),
            'nickname': forms.TextInput(attrs={'placeholder': 'Иван'}),
        }


class EventForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Event
        fields = ('date', 'description')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'description': forms.TextInput(attrs={'placeholder': 'Поездка на дачу'}),
        }


class PurchaseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ('event', 'person', 'description', 'amount')
        widgets = {
            'description': forms.TextInput(
                attrs={'placeholder': 'Продукты, поездка на такси и т.п.'},
            ),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['event'].queryset = Event.objects.all()
        self.fields['person'].queryset = Person.objects.all()
