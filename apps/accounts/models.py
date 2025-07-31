from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db import models

# Create your models here.
class User(AbstractUser):
    is_admin = models.BooleanField(default=False)
    
class Lojista(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)

    def __str__(self):
        # return '%s %s - %s'%(self.user.first_name, self.user.last_name, self.user.specialization)
        return (
            str(self.user.first_name)
            + " "
            + str(self.user.last_name)
        )