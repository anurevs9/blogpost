import logging
from venv import logger

from django.contrib.auth import logout, login
from django.http import request
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.utils.timezone import now

from .forms import UserRegistrationForm, PostForm
from .models import Post, Subscription, Payment
import razorpay
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def home(request):
    # Only show public posts on the homepage
    posts = Post.objects.filter(author__is_active=True).order_by('-created_date')
    return render(request, 'blog/home.html', {'posts': posts})


def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Registration successful! Welcome to MyBlog.')
            return redirect('dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserRegistrationForm()
    return render(request, 'blog/register.html', {'form': form})

@login_required
def dashboard(request):
    user_posts = Post.objects.filter(author=request.user).order_by('-created_date')
    subscription = Subscription.objects.filter(user=request.user, is_active=True).first()
    return render(request, 'blog/dashboard.html', {
        'posts': user_posts,
        'subscription': subscription
    })


@login_required
def create_post(request):
    if request.method == 'POST':
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            messages.success(request, 'Post created successfully!')
            return redirect('post_success')
    else:
        form = PostForm()
    return render(request, 'blog/create_post.html', {'form': form})


@login_required
def edit_post(request, pk):
    post = get_object_or_404(Post, pk=pk, author=request.user)
    if request.method == 'POST':
        form = PostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            form.save()
            messages.success(request, 'Post updated successfully!')
            return redirect('dashboard')
    else:
        form = PostForm(instance=post)
    return render(request, 'blog/edit_post.html', {'form': form})


@login_required
def delete_post_confirm(request, pk):
    post = get_object_or_404(Post, pk=pk, author=request.user)
    if request.method == 'POST':
        post.delete()
        messages.success(request, 'Post deleted successfully!')
        return redirect('dashboard')
    return render(request, 'blog/delete_post_confirm.html', {'post': post})


@login_required
def subscription(request):
    plans = [
        {
            'name': 'Basic',
            'price': 99,
            'monthly_posts': 30,
            'features': {
                'subscriber_conversion': False,
                'paywalls': False,
                'payment_schedules': False
            }
        },
        {
            'name': 'Standard',
            'price': 199,
            'monthly_posts': 100,
            'features': {
                'subscriber_conversion': True,
                'paywalls': False,
                'payment_schedules': False
            }
        },
        {
            'name': 'Premium',
            'price': 299,
            'monthly_posts': 'unlimited',
            'features': {
                'subscriber_conversion': True,
                'paywalls': True,
                'payment_schedules': True
            }
        }
    ]
    return render(request, 'blog/subscription.html', {'plans': plans})


@login_required
def payment(request, plan_type):
    # Define available plans and prices (in paise)
    plan_prices = {
        'basic': 9900,  # ₹99 in paise
        'standard': 19900,  # ₹199 in paise
        'premium': 29900  # ₹299 in paise
    }

    # Validate the plan type
    amount = plan_prices.get(plan_type.lower())
    if not amount:
        logger.error(f"Invalid plan type requested: {plan_type}")
        return redirect('subscription')  # Redirect to subscription page if plan type is invalid

    # Initialize Razorpay client
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    try:
        # Create Razorpay order
        payment_data = {
            'amount': amount,
            'currency': 'INR',
            'receipt': f'receipt_{request.user.id}_{int(datetime.now().timestamp())}',
            'notes': {
                'user_id': request.user.id,
                'plan_type': plan_type
            }
        }
        order = client.order.create(data=payment_data)

        # Log the order creation
        logger.info(f"Order created: {order['id']} for user {request.user.username}")

        # Pass necessary data to the template
        context = {
            'order_id': order['id'],
            'amount': amount / 100,  # Convert to rupees for display
            'key': settings.RAZORPAY_KEY_ID,
            'plan_type': plan_type
        }
        return render(request, 'blog/payment.html', context)

    except razorpay.errors.RazorpayError as e:
        # Log the error
        logger.error(f"Razorpay error: {e}")
        return redirect('subscription')



@login_required
def payment_success(request):
    payment_id = request.GET.get('payment_id')
    order_id = request.GET.get('order_id')
    signature = request.GET.get('signature')
    plan_type = request.GET.get('plan_type')

    if not all([payment_id, order_id, signature, plan_type]):
        messages.error(request, "Invalid payment details received.")
        return redirect('subscription')

    try:
        # Validate Razorpay signature
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })

        # Save Payment Record
        payment = Payment.objects.create(
            user=request.user,
            payment_id=payment_id,
            amount=get_plan_amount(plan_type),
            status='completed'
        )

        # Create or Update Subscription
        end_date = datetime.now() + timedelta(days=30)
        subscription, created = Subscription.objects.get_or_create(
            user=request.user,
            defaults={'plan_type': plan_type, 'end_date': end_date, 'is_active': True}
        )
        if not created:
            subscription.plan_type = plan_type
            subscription.end_date = end_date
            subscription.is_active = True
            subscription.save()

        logger.info(f"Payment successful: {payment}")
        messages.success(request, f"Thank you for subscribing to the {plan_type} plan!")
        return render(request, 'blog/payment_success.html', {
            'subscription': subscription,
            'payment': payment
        })

    except razorpay.errors.SignatureVerificationError as e:
        logger.error(f"Payment signature verification failed: {e}")
        messages.error(request, "Payment verification failed. Please contact support.")
        return redirect('subscription')

    except Exception as e:
        logger.error(f"Error processing payment: {e}")
        messages.error(request, "An error occurred while processing your payment. Please try again.")
        return redirect('subscription')

def get_plan_amount(plan_type):
    plan_prices = {
        'basic': 99.00,
        'standard': 199.00,
        'premium': 299.00
    }
    return plan_prices.get(plan_type.lower(), 99.00)


def payment_error(request):
    return render(request, 'blog/payment_error.html')


def post_success(request):
    return render(request, 'blog/post_success.html')


def about(request):
    return render(request, 'blog/about.html')


def contact(request):
    if request.method == 'POST':
        # Handle contact form submission here
        messages.success(request, 'Your message has been sent successfully!')
        return redirect('contact')
    return render(request, 'blog/contact.html')


def privacy_policy(request):
    return render(request, 'blog/privacy_policy.html')


def terms(request):
    return render(request, 'blog/terms.html')

@login_required
def custom_logout(request):
    logout(request)
    # Clear any existing messages to prevent old messages from showing
    storage = messages.get_messages(request)
    storage.used = True
    # Add logout success message
    messages.success(request, 'You have been successfully logged out.')
    # Redirect to home with a fresh session
    response = redirect('home')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response