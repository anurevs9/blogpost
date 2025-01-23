from django.contrib import admin
from .models import Post, Subscription, Payment

@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'created_date')
    list_filter = ('created_date', 'author')
    search_fields = ('title', 'content')
    date_hierarchy = 'created_date'

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan_type', 'start_date', 'end_date', 'is_active')
    list_filter = ('plan_type', 'is_active')
    search_fields = ('user__username', 'user__email')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('user', 'payment_id', 'amount', 'timestamp', 'status')
    list_filter = ('status', 'timestamp')
    search_fields = ('user__username', 'payment_id')

