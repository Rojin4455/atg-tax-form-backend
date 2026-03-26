from django.contrib import admin
from django.utils.html import format_html
from .models import (
    UserProfile,
    EstatePlanningSubmission,
)

admin.site.register(UserProfile)


@admin.register(EstatePlanningSubmission)
class EstatePlanningSubmissionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'current_step', 'submitted_at', 'updated_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'user__email', 'id')
    ordering = ('-updated_at',)
    readonly_fields = ('id', 'user', 'submitted_at', 'created_at', 'updated_at')

    fieldsets = (
        ('Submission Info', {
            'fields': ('id', 'user', 'status', 'current_step', 'submitted_at', 'created_at', 'updated_at'),
        }),
        ('Step 1 — Personal Information', {
            'classes': ('collapse',),
            'fields': ('step1_personal',),
        }),
        ('Step 2 — Heirs & Legal', {
            'classes': ('collapse',),
            'fields': ('step2_heirs_legal',),
        }),
        ('Step 3 — Trust Distribution', {
            'classes': ('collapse',),
            'fields': ('step3_distribution',),
        }),
        ('Step 4 — Financial, Business & Property', {
            'classes': ('collapse',),
            'fields': ('step4_financials',),
        }),
        ('Internal Staff Notes', {
            'fields': ('staff_notes',),
        }),
    )
