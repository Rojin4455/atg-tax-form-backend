from django.core.management.base import BaseCommand
from accounts.services import pull_all_customfields_standalone

class Command(BaseCommand):
    help = 'Fetch and pull custom fields from GoHighLevel API for all valid locations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type=str,
            default='all',
            help='Specific GHL model to fetch custom fields for (default: all)'
        )

    def handle(self, *args, **options):
        model = options.get('model')
        
        self.stdout.write(self.style.SUCCESS(f'Starting to pull custom fields for model: {model}'))
        
        try:
            summary = pull_all_customfields_standalone(model=model)
            
            if not summary:
                self.stdout.write(self.style.WARNING('No custom fields were pulled. Check if valid GHL Auth Credentials exist.'))
            else:
                for msg in summary:
                    if 'Failed' in msg:
                        self.stdout.write(self.style.ERROR(msg))
                    else:
                        self.stdout.write(self.style.SUCCESS(msg))
                        
            self.stdout.write(self.style.SUCCESS('Custom fields pull process completed.'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'An error occurred: {str(e)}'))
