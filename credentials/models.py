from django.db import models
from django.utils import timezone
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, UserManager

class CustomUser(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(
        "Username",
        max_length=100,
        unique=True
    )
    email = models.EmailField(
        "Email address",
        max_length=255,
        null=True,
        blank=True
    )
    is_staff = models.BooleanField(
        "Staff status",
        default=False
    )
    is_active = models.BooleanField(
        "Active",
        default=True
    )
    date_joined = models.DateTimeField(
        "Date joined",
        default=timezone.now
    )
    user_groups = models.JSONField(
        null=True,
        blank=False
    )

    objects = UserManager()
    USERNAME_FIELD = 'username'
    EMAIL_FIELD = 'email'

class Profile(models.Model):
    global_id = models.CharField(max_length=50, unique=True)
    username = models.CharField(max_length=100)
    account = models.OneToOneField(CustomUser, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.username if self.username else "No username"
