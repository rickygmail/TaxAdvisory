def calculate_old_regime(data):
    # Extract and convert values
    gross_salary = float(data.get('gross_salary', 0) or 0)
    basic_salary = float(data.get('basic_salary', 0) or 0)
    hra_received = float(data.get('hra_received', 0) or 0)
    rent_paid = float(data.get('rent_paid', 0) or 0)
    deduction_80c = float(data.get('deduction_80c', 0) or 0)
    deduction_80d = float(data.get('deduction_80d', 0) or 0)
    standard_deduction = float(data.get('standard_deduction', 50000) or 50000)
    professional_tax = float(data.get('professional_tax', 0) or 0)
    tds = float(data.get('tds', 0) or 0)

    # Old regime deductions
    total_deductions = standard_deduction + hra_received + professional_tax + deduction_80c + deduction_80d
    taxable_income = max(gross_salary - total_deductions, 0)

    # Old regime slabs
    tax = 0
    if taxable_income > 250000:
        if taxable_income <= 500000:
            tax = 0.05 * (taxable_income - 250000)
        elif taxable_income <= 1000000:
            tax = 0.05 * 250000 + 0.2 * (taxable_income - 500000)
        else:
            tax = 0.05 * 250000 + 0.2 * 500000 + 0.3 * (taxable_income - 1000000)
    # 4% cess
    tax = tax * 1.04
    return round(tax, 2), round(taxable_income, 2), round(total_deductions, 2)

def calculate_new_regime(data):
    gross_salary = float(data.get('gross_salary', 0) or 0)
    standard_deduction = float(data.get('standard_deduction', 50000) or 50000)
    taxable_income = max(gross_salary - standard_deduction, 0)
    # New regime slabs
    tax = 0
    slabs = [
        (300000, 0.0),
        (600000, 0.05),
        (900000, 0.10),
        (1200000, 0.15),
        (1500000, 0.20),
        (float('inf'), 0.30)
    ]
    prev_limit = 0
    for limit, rate in slabs:
        if taxable_income > limit:
            tax += (limit - prev_limit) * rate
            prev_limit = limit
        else:
            tax += (taxable_income - prev_limit) * rate
            break
    # 4% cess
    tax = tax * 1.04
    return round(tax, 2), round(taxable_income, 2), standard_deduction 