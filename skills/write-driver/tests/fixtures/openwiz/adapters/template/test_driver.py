"""A synthetic stand-in for the template's own tests: it names the state variable a copy renames."""
import os
STATE = os.environ.get('OPENWIZ_TEMPLATE_STATE')
RUN = 'python3 -I adapters/template/test_driver.py'
