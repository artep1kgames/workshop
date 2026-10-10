from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("receipt/new/", views.new_receipt, name="new_receipt"),
    path("receipt/create/", views.create_receipt, name="create_receipt"),
    path("day/close/", views.close_day, name="close_day"),
    path("day/reopen/", views.reopen_day, name="reopen_day"),
    path("receipt/<int:receipt_id>/edit/", views.edit_receipt, name="edit_receipt"),
]
