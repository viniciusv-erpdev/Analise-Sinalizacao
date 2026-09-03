from django.contrib import admin

from signaling.models import SignalingIntervention, SignalingPoint


admin.site.register(SignalingPoint)
admin.site.register(SignalingIntervention)
