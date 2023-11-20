from django.shortcuts import render


def homePage(request):
    context = {}
    return render(request, 'linguich/index.html', context)


def stockPage(request):
    context = {}
    return render(request, 'linguich/stock.html', context)
