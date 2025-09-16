from FreeCAD import Units


_linear_orthotropic_parms = [
    "PoissonRatioXY",
    "PoissonRatioXZ",
    "PoissonRatioYZ",
    "ShearModulusXY",
    "ShearModulusXZ",
    "ShearModulusYZ",
    "YoungsModulusX",
    "YoungsModulusY",
    "YoungsModulusZ",
]


def is_linear_orthotropic(material):
    for i in _linear_orthotropic_parms:
        if i not in material:
            return False
    return True


def check_linear_isotropic(mat_map):
    message = ""
    if "YoungsModulus" in mat_map:
        # print(Units.Quantity(mat_map["YoungsModulus"]).Value)
        if not Units.Quantity(mat_map["YoungsModulus"]).Value:
            message += "Value of YoungsModulus is set to 0.0.\n"
    else:
        message += "No YoungsModulus defined for at least one material.\n"
    if "PoissonRatio" not in mat_map:
        # PoissonRatio is allowed to be 0.0 (in ccx), but it should be set anyway.
        message += "No PoissonRatio defined for at least one material.\n"
    return message


def check_linear_orthotropic(mat_map):
    message = ""
    for item in _linear_orthotropic_parms:
        if not Units.Quantity(mat_map[item]).Value:
            message += f"Value of {item} is non-positive.\n"
    return message


def check_linear_material(mat_map):
    if is_linear_orthotropic(mat_map):
        return check_linear_orthotropic(mat_map)
    else:
        return check_linear_isotropic(mat_map)
