"""LoanerPlatform — loaner fleet mileage updating, pricing, and payment reporting.

Pipeline:
    1. Parse the TSD Full Inventory Report (current miles per active unit).
    2. Parse the vAuto Payment Calculator export (all loaners, incl. retired).
    3. Parse the Simple Calculator workbook (rates, residuals, programs, discounts).
    4. Reprice every unit using the greater of the vAuto odometer and TSD miles.
    5. Render an HTML email with the loaner sheet.
"""

__version__ = "1.0.0"
