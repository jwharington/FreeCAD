// SPDX-License-Identifier: LGPL-2.1-or-later
/****************************************************************************
 *                                                                          *
 *   Copyright (c) 2023 Ondsel <development@ondsel.com>                     *
 *                                                                          *
 *   This file is part of FreeCAD.                                          *
 *                                                                          *
 *   FreeCAD is free software: you can redistribute it and/or modify it     *
 *   under the terms of the GNU Lesser General Public License as            *
 *   published by the Free Software Foundation, either version 2.1 of the   *
 *   License, or (at your option) any later version.                        *
 *                                                                          *
 *   FreeCAD is distributed in the hope that it will be useful, but         *
 *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
 *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
 *   Lesser General Public License for more details.                        *
 *                                                                          *
 *   You should have received a copy of the GNU Lesser General Public       *
 *   License along with FreeCAD. If not, see                                *
 *   <https://www.gnu.org/licenses/>.                                       *
 *                                                                          *
 ***************************************************************************/

#include <boost/core/ignore_unused.hpp>
#include <cmath>
#include <cstdlib>
#include <optional>
#include <vector>
#include <unordered_map>


#include <App/Application.h>
#include <App/Datums.h>
#include <App/Document.h>
#include <App/DocumentObjectGroup.h>
#include <App/FeaturePythonPyImp.h>
#include <App/Link.h>
#include <App/PropertyPythonObject.h>
#include <App/PropertyLinks.h>
#include <App/PropertyStandard.h>
#include <Base/Console.h>
#include <Base/Placement.h>
#include <Base/Quantity.h>
#include <Base/Rotation.h>
#include <Base/Tools.h>
#include <Base/Interpreter.h>

#include <Mod/Part/App/TopoShape.h>
#include <Mod/Part/App/Attacher.h>
#include <Mod/Part/App/AttachExtension.h>
#include <Mod/Part/App/PartFeature.h>
#include <GProp_GProps.hxx>
#include <GProp_PrincipalProps.hxx>

#include <FreeCADMbD/ASMTSimulationParameters.h>
#include <FreeCADMbD/ASMTAssembly.h>
#include <FreeCADMbD/ASMTMarker.h>
#include <FreeCADMbD/ASMTPart.h>
#include <FreeCADMbD/ASMTJoint.h>
#include <FreeCADMbD/JointIJ.h>
#include <FreeCADMbD/ASMTAngleJoint.h>
#include <FreeCADMbD/ASMTFixedJoint.h>
#include <FreeCADMbD/ASMTGearJoint.h>
#include <FreeCADMbD/ASMTRevoluteJoint.h>
#include <FreeCADMbD/ASMTCylindricalJoint.h>
#include <FreeCADMbD/ASMTTranslationalJoint.h>
#include <FreeCADMbD/ASMTSphericalJoint.h>
#include <FreeCADMbD/ASMTParallelAxesJoint.h>
#include <FreeCADMbD/ASMTPerpendicularJoint.h>
#include <FreeCADMbD/ASMTPointInPlaneJoint.h>
#include <FreeCADMbD/ASMTPointInLineJoint.h>
#include <FreeCADMbD/ASMTLineInPlaneJoint.h>
#include <FreeCADMbD/ASMTPlanarJoint.h>
#include <FreeCADMbD/ASMTRevCylJoint.h>
#include <FreeCADMbD/ASMTCylSphJoint.h>
#include <FreeCADMbD/ASMTRackPinionJoint.h>
#include <FreeCADMbD/ASMTRotationLimit.h>
#include <FreeCADMbD/ASMTTranslationLimit.h>
#include <FreeCADMbD/ASMTRotationalMotion.h>
#include <FreeCADMbD/ASMTTranslationalMotion.h>
#include <FreeCADMbD/ASMTGeneralMotion.h>
#include <FreeCADMbD/ASMTScrewJoint.h>
#include <FreeCADMbD/ASMTSphSphJoint.h>
#include <FreeCADMbD/ASMTTime.h>
#include <FreeCADMbD/ASMTConstantGravity.h>
#include <FreeCADMbD/ASMTForceTorqueGeneral.h>
#include <FreeCADMbD/ASMTForceTorqueInLine.h>
#include <FreeCADMbD/ExternalSystem.h>
#include <FreeCADMbD/enum.h>
#include <FreeCADMbD/MomentOfInertiaSolver.h>

#include "AssemblyLink.h"
#include "AssemblyObject.h"
#include "AssemblyObjectPy.h"
#include "AssemblyUtils.h"
#include "JointGroup.h"
#include "ForceGroup.h"
#include "ViewGroup.h"

FC_LOG_LEVEL_INIT("Assembly", true, true, true)

using namespace Assembly;
using namespace MbD;


namespace PartApp = Part;

namespace
{

template<typename T>
void setMarkerICompat(const std::shared_ptr<T>& item, const std::shared_ptr<MbD::ASMTMarker>& marker)
{
    item->setMarkerI(marker);
}

template<typename T>
void setMarkerJCompat(const std::shared_ptr<T>& item, const std::shared_ptr<MbD::ASMTMarker>& marker)
{
    item->setMarkerJ(marker);
}

bool parseDensityTonPerMm3(const std::string& densityText, double& densityOut)
{
    try {
        const Base::Quantity densityQuantity = Base::Quantity::parse(densityText);
        const Base::Quantity densityUnit = Base::Quantity::parse("1 t/mm^3");
        densityOut = densityQuantity.getValueAs(densityUnit);
        return std::isfinite(densityOut) && densityOut > 0.0;
    }
    catch (...) {
        return false;
    }
}

bool materialReferenceMatches(
    App::DocumentObject* targetPart,
    App::DocumentObject* targetLinked,
    App::DocumentObject* referenceObj
)
{
    if (!referenceObj) {
        return false;
    }

    if (referenceObj == targetPart || referenceObj == targetLinked) {
        return true;
    }

    if (auto* referenceLink = dynamic_cast<App::Link*>(referenceObj)) {
        App::DocumentObject* linked = referenceLink->getLinkedObject();
        if (linked && (linked == targetPart || linked == targetLinked)) {
            return true;
        }
    }

    return false;
}

std::optional<double> getEnvDouble(const char* name)
{
    if (!name || !*name) {
        return std::nullopt;
    }

    const char* raw = std::getenv(name);
    if (!raw || !*raw) {
        return std::nullopt;
    }

    try {
        size_t consumed = 0;
        const std::string text(raw);
        const double value = std::stod(text, &consumed);
        if (consumed != text.size() || !std::isfinite(value)) {
            return std::nullopt;
        }
        return value;
    }
    catch (...) {
        return std::nullopt;
    }
}

std::string getEnvString(const char* name)
{
    if (!name || !*name) {
        return std::string();
    }

    const char* raw = std::getenv(name);
    return (raw && *raw) ? std::string(raw) : std::string();
}

std::optional<double> getFemMaterialDensityTonPerMm3(
    App::DocumentObject* targetPart,
    App::DocumentObject* targetLinked
)
{
    if (!targetPart) {
        return std::nullopt;
    }

    App::Document* doc = targetPart->getDocument();
    if (!doc) {
        return std::nullopt;
    }

    std::optional<double> globalDensity;

    for (App::DocumentObject* obj : doc->getObjects()) {
        if (!obj) {
            continue;
        }

        auto* materialProp = dynamic_cast<App::PropertyMap*>(obj->getPropertyByName("Material"));
        if (!materialProp) {
            continue;
        }

        const auto& materialValues = materialProp->getValues();
        auto densityIt = materialValues.find("Density");
        if (densityIt == materialValues.end()) {
            continue;
        }

        double densityCandidate = 0.0;
        if (!parseDensityTonPerMm3(densityIt->second, densityCandidate)) {
            continue;
        }

        auto* referencesProp = dynamic_cast<App::PropertyLinkSubList*>(
            obj->getPropertyByName("References")
        );

        if (!referencesProp) {
            if (!globalDensity) {
                globalDensity = densityCandidate;
            }
            continue;
        }

        const auto& references = referencesProp->getValues();
        if (references.empty()) {
            if (!globalDensity) {
                globalDensity = densityCandidate;
            }
            continue;
        }

        for (App::DocumentObject* refObj : references) {
            if (materialReferenceMatches(targetPart, targetLinked, refObj)) {
                return densityCandidate;
            }
        }
    }

    return globalDensity;
}

}  // namespace


// ================================ Assembly Object ============================

PROPERTY_SOURCE(Assembly::AssemblyObject, App::Part)

AssemblyObject::AssemblyObject()
    : mbdAssembly(std::make_shared<ASMTAssembly>())
    , bundleFixed(false)
    , lastDoF(0)
    , lastHasConflict(false)
    , lastHasRedundancies(false)
    , lastHasPartialRedundancies(false)
    , lastHasMalformedConstraints(false)
    , lastSolverStatus(0)
{
    lastDoF = numberOfComponents() * 6;
    signalSolverUpdate();
}

AssemblyObject::~AssemblyObject() = default;

PyObject* AssemblyObject::getPyObject()
{
    if (PythonObject.is(Py::_None())) {
        // ref counter is set to 1
        PythonObject = Py::Object(new AssemblyObjectPy(this), true);
    }
    return Py::new_reference_to(PythonObject);
}

App::DocumentObjectExecReturn* AssemblyObject::execute()
{
    App::DocumentObjectExecReturn* ret = App::Part::execute();

    ParameterGrp::handle hGrp = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Assembly"
    );
    if (hGrp->GetBool("SolveOnRecompute", true)) {
        solve(false);
    }
    return ret;
}

void AssemblyObject::onChanged(const App::Property* prop)
{
    if (prop == &Group) {
        updateSolveStatus();
    }
    App::Part::onChanged(prop);
}

int AssemblyObject::solve(bool enableRedo)
{
    ensureIdentityPlacements();

    syncGroundedJoints();

    mbdAssembly = makeMbdAssembly();
    objectPartMap.clear();
    objectJointMap.clear();
    motions.clear();

    auto groundedObjs = fixGroundedParts();
    if (groundedObjs.empty()) {
        // If no part fixed we can't solve.
        return -6;
    }

    std::vector<App::DocumentObject*> joints = getJoints();

    removeUnconnectedJoints(joints, groundedObjs);

    jointParts(joints);

    std::vector<App::DocumentObject*> forces = getForces();
    forceParts(forces);

    if (enableRedo) {
        savePlacementsForUndo();
    }

    try {
        mbdAssembly->runPreDrag();
        lastSolverStatus = 0;
    }
    catch (const std::exception& e) {
        FC_ERR("Solve failed: " << e.what());
        lastSolverStatus = -1;
        updateSolveStatus();
        return -1;
    }
    catch (...) {
        FC_ERR("Solve failed: unhandled exception");
        lastSolverStatus = -1;
        updateSolveStatus();
        return -1;
    }

    setNewPlacements();

    redrawJointPlacements(joints);

    updateSolveStatus();

    return 0;
}

void AssemblyObject::updateSolveStatus()
{
    lastRedundantJoints.clear();
    lastHasRedundancies = false;
    //+1 because there's a grounded joint to origin
    lastDoF = (1 + numberOfComponents()) * 6;

    if (!mbdAssembly || !mbdAssembly->mbdSystem) {
        solve();
    }

    if (!mbdAssembly || !mbdAssembly->mbdSystem) {
        return;
    }

    // Helper lambda to clean up the joint name from the solver
    auto cleanJointName = [](const std::string& rawName) -> std::string {
        // rawName is like : /OndselAssembly/ground_moves#Joint001
        size_t hashPos = rawName.find_last_of('#');
        if (hashPos != std::string::npos) {
            // Return the substring after the '#'
            return rawName.substr(hashPos + 1);
        }
        return rawName;
    };


    // Iterate through all joints and motions in the MBD system
    mbdAssembly->mbdSystem->jointsMotionsLimitsDo([&](std::shared_ptr<MbD::ConstraintSet> jm) {
        if (!jm) {
            return;
        }
        // Base::Console().warning("jm->name %s\n", jm->name);
        bool isJointRedundant = false;

        jm->constraintsDo([&](std::shared_ptr<MbD::Constraint> con) {
            if (!con) {
                return;
            }

            std::string spec = con->constraintSpec();
            // A constraint is redundant if its spec starts with "Redundant"
            if (spec.rfind("Redundant", 0) == 0) {
                isJointRedundant = true;
            }
            // Base::Console().warning("    - %s\n", spec);
            --lastDoF;
        });

        const std::string fullName = cleanJointName(jm->name);
        App::DocumentObject* docObj = getDocument()->getObject(fullName.c_str());

        // We only care about objects that are actual joints in the FreeCAD document.
        // This effectively filters out the grounding joints, which are named after parts.
        if (!docObj || !docObj->getPropertyByName("Reference1")) {
            return;
        }

        if (isJointRedundant) {
            // Check if this joint is already in the list to avoid duplicates
            std::string objName = docObj->getNameInDocument();
            if (std::find(lastRedundantJoints.begin(), lastRedundantJoints.end(), objName)
                == lastRedundantJoints.end()) {
                lastRedundantJoints.push_back(objName);
            }
        }
    });

    // Update the summary boolean flag
    if (!lastRedundantJoints.empty()) {
        lastHasRedundancies = true;
    }

    signalSolverUpdate();
}

int AssemblyObject::generateSimulation(App::DocumentObject* sim)
{
    mbdAssembly = makeMbdAssembly();
    objectPartMap.clear();
    objectJointMap.clear();

    motions = getMotionsFromSimulation(sim);

    auto groundedObjs = fixGroundedParts();
    if (groundedObjs.empty()) {
        // If no part fixed we can't solve.
        return -6;
    }

    std::vector<App::DocumentObject*> joints = getJoints();

    removeUnconnectedJoints(joints, groundedObjs);

    jointParts(joints);

    std::vector<App::DocumentObject*> forces = getForces();
    forceParts(forces);

    create_mbdSimulationParameters(sim);

    {
        double g = -9810.0;
        auto* gprop = dynamic_cast<App::PropertyFloat*>(
            sim->getPropertyByName("GravitationalAcceleration")
        );
        if (gprop) {
            g = gprop->getValue();
        }
        else {
            g = App::GetApplication()
                    .GetParameterGroupByPath("User parameter:BaseApp/Preferences/Mod/Assembly")
                    ->GetFloat("GravitationalAcceleration", g);
        }

        if (auto gOverride = getEnvDouble("FREECAD_ASSEMBLY_G_OVERRIDE")) {
            g = *gOverride;
        }
        if (auto gScale = getEnvDouble("FREECAD_ASSEMBLY_G_SCALE")) {
            g *= *gScale;
        }

        auto constantGravity = ASMTConstantGravity::With();
        auto gAcceleration = std::make_shared<FullColumn<double>>(ListD {0.0, 0.0, g});
        constantGravity->setg(gAcceleration);
        mbdAssembly->setConstantGravity(constantGravity);
    }

    auto* prop = dynamic_cast<App::PropertyBool*>(sim->getPropertyByName("Dynamic"));
    const bool dynamic = (prop && prop->getValue());
    int retval = 0;

    try {
        if (dynamic) {
            mbdAssembly->runDYNAMIC();
        }
        else {
            mbdAssembly->runKINEMATIC();
        }
    }
    catch (const std::exception& e) {
        FC_ERR("Simulation failed: " << e.what());
        retval = -1;
    }
    catch (...) {
        FC_ERR("Solve failed: unhandled exception");
        retval = -1;
    }
    if (retval < 0) {
        Base::Console().error("Generation of simulation failed\n");
    }

    motions.clear();

    return 0;
}


AssemblyObject::JointPartInfo AssemblyObject::getJointPart(App::DocumentObject* joint, const int index)
{
    const char* ref_name = (index == 0) ? "Reference1" : "Reference2";
    const char* plc_name = (index == 0) ? "Placement1" : "Placement2";
    JointPartInfo info;
    info.joint = joint;
    info.jointName = joint->getFullLabel();  // getNameInDocument();
    auto* pPlc = dynamic_cast<App::PropertyPlacement*>(joint->getPropertyByName(plc_name));
    if (pPlc) {
        info.placement = pPlc->getValue();
    }
    info.part = getMovingPartFromRef(joint, ref_name);
    if (!info.part) {
        info.part = getObjFromRef(joint, ref_name);
    }
    if (!info.part) {
        auto* pJoint = dynamic_cast<App::PropertyXLinkSub*>(joint->getPropertyByName("Joint"));
        if (pJoint) {
            App::DocumentObject* motionJoint = pJoint->getValue();
            return getJointPart(motionJoint, index);
        }
    }
    return info;
}


std::ostream& operator<<(std::ostream& os, const Base::Vector3d& vector)
{
    os << vector.x << " " << vector.y << " " << vector.z;
    return os;
}


Base::Vector3d m2f(FColDsptr vec)
{
    return Base::Vector3d(vec->at(0), vec->at(1), vec->at(2));
}


void AssemblyObject::ReactionInfo::print() const
{
    std::cout << "    Reaction at joint: " << jointInfo.jointName << "\n";
    std::cout << "      position: " << position << "\n";
    std::cout << "      force:    " << force << "\n";
    std::cout << "      torque:   " << torque << "\n";
    std::cout << "      side:   " << side << "\n";
}


void setJointProperty(
    App::DocumentObject* joint,
    const Base::Vector3d& vec,
    const char* propName,
    const int side,
    const bool acc = false
)
{
    const std::string suffix = std::to_string(side + 1);
    const std::string fullPropName = std::string(propName) + suffix;
    const std::string groupName = std::string("Reaction") + suffix;
    App::Property* prop = joint->getPropertyByName(fullPropName.c_str());
    if (!prop) {
        prop = joint->addDynamicProperty(
            "App::PropertyVector",
            fullPropName.c_str(),
            groupName.c_str(),
            nullptr,
            App::Prop_ReadOnly
        );
    }
    if (prop) {
        auto vprop = dynamic_cast<App::PropertyVector*>(prop);
        if (vprop) {
            if (acc) {
                vprop->setValue(vec + vprop->getValue());
            }
            else {
                vprop->setValue(Base::Vector3d(0, 0, 0));
            }
        }
    }
}


void setBodyPropertyScalar(App::DocumentObject* body, const double value, const char* propName)
{
    App::Property* prop = body->getPropertyByName(propName);
    if (!prop) {
        prop = body->addDynamicProperty(
            "App::PropertyFloat",
            propName,
            "Dynamics",
            nullptr,
            App::Prop_ReadOnly
        );
    }
    if (prop) {
        auto vprop = dynamic_cast<App::PropertyFloat*>(prop);
        if (vprop) {
            vprop->setValue(value);
        }
    }
}


void setBodyProperty(App::DocumentObject* body, const Base::Vector3d& vec, const char* propName)
{
    App::Property* prop = body->getPropertyByName(propName);
    if (!prop) {
        prop = body->addDynamicProperty(
            "App::PropertyVector",
            propName,
            "Dynamics",
            nullptr,
            App::Prop_ReadOnly
        );
    }
    if (prop) {
        auto vprop = dynamic_cast<App::PropertyVector*>(prop);
        if (vprop) {
            vprop->setValue(vec);
        }
    }
}


AssemblyObject::ReactionInfo AssemblyObject::getReactionInfo(
    const AssemblyObject::JointPartInfo& info,
    const Base::Vector3d& cFIO,
    const Base::Vector3d& cTIO,
    const int side
)
{
    const Base::Placement base_plc = getPlacementFromProp(info.part->getLinkedObject(), "Placement");
    const Base::Placement body_plc = getPlacementFromProp(info.part, "Placement").inverse();
    ReactionInfo reaction_info;
    reaction_info.jointInfo = info;
    reaction_info.position = (base_plc * info.placement).getPosition();
    const Base::Rotation body_rot = base_plc.getRotation() * body_plc.getRotation();
    reaction_info.force = body_rot.multVec(cFIO);
    reaction_info.torque = body_rot.multVec(cTIO);
    reaction_info.side = side;
    // these are relative to body coords of attached body
    return reaction_info;
}


void AssemblyObject::jointInfoForFrame(const size_t index)
{
    std::unordered_map<App::DocumentObject*, std::vector<ReactionInfo>> objectReactionMap;

    for (auto& pair : objectJointMap) {
        App::DocumentObject* joint = pair.first;
        auto mbdItemIJ = pair.second.joint;

        // aFIO = F on I, aTIO = T on I
        // std::cout << "item " << mbdItemIJ->name << " index: " << index << std::endl;
        try {
            const Base::Vector3d aFIO = m2f(mbdItemIJ->aFIO(index));
            // std::cout << "    inertial F: " << aFIO << "\n" << std::flush;

            const Base::Vector3d aTIO = m2f(mbdItemIJ->aTIO(index));
            // std::cout << "    inertial T: " << aTIO << "\n" << std::flush;

            for (int j = 0; j < 2; j++) {
                const JointPartInfo info = getJointPart(joint, j);
                if (!info.part) {
                    std::cout << "    no part for side " << j << " of joint "
                              << joint->getFullName() << "\n";
                    continue;
                }

                const float sign = (j == 0) ? 1.0f : -1.0f;
                const ReactionInfo reaction_info = getReactionInfo(info, aFIO * sign, aTIO * sign, j);
                objectReactionMap[info.part].push_back(reaction_info);
                // these are relative to body coords of attached body
            }
        }
        catch (const std::exception& e) {
            FC_ERR("Simulation failed: " << e.what());
            std::cerr << "exception handling joint info for frame " << index << std::endl
                      << std::flush;
        }
        catch (...) {
            std::cerr << "exception handling joint info for frame " << index << std::endl
                      << std::flush;
        }
    }

    // std::cout << "time: " << index << "\n";
    // std::cout << std::flush;

    for (auto& pair : objectReactionMap) {
        App::DocumentObject* part = pair.first;
        std::shared_ptr<ASMTPart> mbdPart = nullptr;
        for (auto& o_pair : objectPartMap) {
            App::DocumentObject* o_part = o_pair.first;
            if (o_part == part) {
                mbdPart = o_pair.second.part;
                break;
            }
        }
        if (!mbdPart) {
            continue;
        }
        double x, y, z;
        mbdPart->principalMassMarker->getPosition3D(x, y, z);

        const Base::Placement base_plc = getPlacementFromProp(part->getLinkedObject(), "Placement");
        const Base::Placement body_plc = getPlacementFromProp(part, "Placement").inverse();
        const Base::Rotation body_rot = base_plc.getRotation() * body_plc.getRotation();
        const Base::Vector3d com = base_plc.toMatrix() * Base::Vector3d(x, y, z);

        const double mass = mbdPart->principalMassMarker->mass;
        setBodyPropertyScalar(part, mass * 1000.0, "Mass");

        // std::cout << "Part: "
        //           << part->getFullLabel()
        //           // << " mass: " << mass
        //           << std::endl
        //           << std::flush;

        // std::cout << "  Position of Mass Center: " << com << "\n";

        const Base::Vector3d velocity = body_rot.multVec(m2f(mbdPart->getVelocity3D(index)));
        const Base::Vector3d angularVelocity = body_rot.multVec(m2f(mbdPart->getOmega3D(index)));
        const Base::Vector3d rawAcceleration = body_rot.multVec(m2f(mbdPart->getAcceleration3D(index)));
        const Base::Vector3d gravityAcceleration = body_rot.multVec(
            m2f(mbdAssembly->constantGravity->getg())
        );

        Base::Vector3d acceleration = rawAcceleration + gravityAcceleration;
        const std::string accelMode = getEnvString("FREECAD_ASSEMBLY_ACCEL_EXPORT_MODE");
        if (accelMode == "raw") {
            acceleration = rawAcceleration;
        }
        else if (accelMode == "raw_minus_g") {
            acceleration = rawAcceleration - gravityAcceleration;
        }
        else if (accelMode == "raw_plus_g") {
            acceleration = rawAcceleration + gravityAcceleration;
        }

        const Base::Vector3d angularAcceleration = body_rot.multVec(m2f(mbdPart->getAlpha3D(index)));

        // std::cout << "  Velocity:            " << velocity << "\n";
        // std::cout << "  Angular Velocity:    " << angularVelocity << "\n";
        // std::cout << "  Acceleration total:        " << acceleration << "\n";
        // std::cout << "  Acceleration raw:        "
        //           << body_rot.multVec(m2f(mbdPart->getAcceleration3D(index))) << "\n";
        // std::cout << "  Acceleration gravity:        "
        //           << body_rot.multVec(m2f(mbdAssembly->constantGravity->getg())) << "\n";
        // std::cout << std::flush;
        // std::cout << "  Angular Acceleration:" << angularAcceleration << "\n";

        setBodyProperty(part, com, "CenterOfMass");
        setBodyProperty(part, velocity, "LinearVelocity");
        setBodyProperty(part, angularVelocity, "AngularVelocity");
        setBodyProperty(part, acceleration, "LinearAcceleration");
        setBodyProperty(part, angularAcceleration, "AngularAcceleration");


        for (int acc = 0; acc < 2; ++acc) {
            for (auto& reaction_info : pair.second) {
                // reaction_info.print();
                setJointProperty(
                    reaction_info.jointInfo.joint,
                    reaction_info.position,
                    "Origin",
                    reaction_info.side,
                    acc
                );
            }
        }

        for (int acc = 0; acc < 2; ++acc) {
            for (auto& reaction_info : pair.second) {
                setJointProperty(
                    reaction_info.jointInfo.joint,
                    reaction_info.force,
                    "Force",
                    reaction_info.side,
                    acc
                );
                setJointProperty(
                    reaction_info.jointInfo.joint,
                    reaction_info.torque,
                    "Torque",
                    reaction_info.side,
                    acc
                );
            }
        }
        // std::cout << std::flush;
    }
}

std::vector<App::DocumentObject*> AssemblyObject::getMotionsFromSimulation(App::DocumentObject* sim)
{
    if (!sim) {
        return {};
    }

    auto* prop = dynamic_cast<App::PropertyLinkList*>(sim->getPropertyByName("Group"));
    if (!prop) {
        return {};
    }

    return prop->getValue();
}

int Assembly::AssemblyObject::updateForFrame(size_t index, bool updateJCS)
{
    // std::cout << "update for frame " << index << "\n";
    if (!mbdAssembly) {
        return -1;
    }

    auto nfrms = numberOfFrames();
    if (index >= nfrms) {
        return -1;
    }

    mbdAssembly->updateForFrame(index);
    setNewPlacements();
    auto jointDocs = getJoints(updateJCS);
    redrawJointPlacements(jointDocs);
    jointInfoForFrame(index);

    auto forceDocs = getForces(updateJCS);
    redrawJointPlacements(forceDocs);

    return 0;
}

size_t Assembly::AssemblyObject::numberOfFrames()
{
    if (mbdAssembly->times == nullptr) {
        return 0;
    }
    return mbdAssembly->times->size();
}

void AssemblyObject::preDrag(std::vector<App::DocumentObject*> dragParts)
{
    bundleFixed = true;
    solve();
    bundleFixed = false;

    draggedParts.clear();
    for (auto part : dragParts) {
        // make sure no duplicate
        if (std::ranges::find(draggedParts, part) != draggedParts.end()) {
            continue;
        }

        // Free-floating parts should not be added since they are ignored by the solver!
        if (!isPartConnected(part)) {
            continue;
        }

        // Some objects have been bundled, we don't want to add these to dragged parts
        Base::Placement plc;
        for (auto& pair : objectPartMap) {
            App::DocumentObject* parti = pair.first;
            if (parti != part) {
                continue;
            }
            plc = pair.second.offsetPlc;
        }
        if (!plc.isIdentity()) {
            // If not identity, then it's a bundled object. Some bundled objects may
            // have identity placement if they have the same position as the main object of
            // the bundle. But they're not going to be a problem.
            continue;
        }

        draggedParts.push_back(part);
    }
}

void AssemblyObject::doDragStep()
{
    try {
        std::vector<std::shared_ptr<MbD::ASMTPart>> dragMbdParts;

        for (auto& part : draggedParts) {
            if (!part) {
                continue;
            }

            auto mbdPart = getMbDPart(part);
            dragMbdParts.push_back(mbdPart);

            // Update the MBD part's position
            Base::Placement plc = getPlacementFromProp(part, "Placement");
            Base::Vector3d pos = plc.getPosition();

            mbdPart->updateMbDFromPosition3D(
                std::make_shared<FullColumn<double>>(ListD {pos.x, pos.y, pos.z})
            );
            // // Update the MBD part's rotation
            Base::Rotation rot = plc.getRotation();
            Base::Matrix4D mat;
            rot.getValue(mat);
            Base::Vector3d r0 = mat.getRow(0);
            Base::Vector3d r1 = mat.getRow(1);
            Base::Vector3d r2 = mat.getRow(2);
            mbdPart->updateMbDFromRotationMatrix(r0.x, r0.y, r0.z, r1.x, r1.y, r1.z, r2.x, r2.y, r2.z);
        }

        // Timing mbdAssembly->runDragStep()
        auto dragPartsVec = std::make_shared<std::vector<std::shared_ptr<ASMTPart>>>(dragMbdParts);
        mbdAssembly->runDragStep(dragPartsVec);

        // Timing the validation and placement setting
        if (validateNewPlacements()) {
            setNewPlacements();

            auto joints = getJoints();
            for (auto* joint : joints) {
                if (joint->Visibility.getValue()) {
                    // redraw only the moving joint as its quite slow as its python code.
                    redrawJointPlacement(joint);
                }
            }
        }
    }
    catch (...) {
        // We do nothing if a solve step fails.
    }
}

Base::Placement AssemblyObject::getMbdPlacement(std::shared_ptr<ASMTPart> mbdPart)
{
    if (!mbdPart) {
        return Base::Placement();
    }

    double x, y, z;
    mbdPart->getPosition3D(x, y, z);
    Base::Vector3d pos = Base::Vector3d(x, y, z);

    double q0, q1, q2, q3;
    mbdPart->getQuarternions(q3, q0, q1, q2);
    Base::Rotation rot = Base::Rotation(q0, q1, q2, q3);

    return Base::Placement(pos, rot);
}

bool AssemblyObject::validateNewPlacements()
{
    // First we check if a grounded object has moved. It can happen that they flip.
    auto groundedParts = getGroundedParts();
    for (auto* obj : groundedParts) {
        auto* propPlacement = obj->getPlacementProperty();
        if (propPlacement) {
            Base::Placement oldPlc = propPlacement->getValue();

            auto it = objectPartMap.find(obj);
            if (it != objectPartMap.end()) {
                std::shared_ptr<MbD::ASMTPart> mbdPart = it->second.part;
                Base::Placement newPlacement = getMbdPlacement(mbdPart);
                if (!it->second.offsetPlc.isIdentity()) {
                    newPlacement = newPlacement * it->second.offsetPlc;
                }

                if (!oldPlc.isSame(newPlacement, Precision::Confusion())) {
                    Base::Console().warning(
                        "Assembly : Ignoring bad solve, a grounded object (%s) moved.\n",
                        obj->getFullLabel()
                    );
                    return false;
                }
            }
        }
    }

    // TODO: We could do further tests
    // For example check if the joints connectors are correctly aligned.
    return true;
}

void AssemblyObject::postDrag()
{
    mbdAssembly->runPostDrag();  // Do this after last drag
    purgeTouched();
}

void AssemblyObject::savePlacementsForUndo()
{
    previousPositions.clear();

    for (auto& pair : objectPartMap) {
        App::DocumentObject* obj = pair.first;
        if (!obj) {
            continue;
        }

        std::pair<App::DocumentObject*, Base::Placement> savePair;
        savePair.first = obj;

        // Check if the object has a "Placement" property
        auto* propPlc = obj->getPlacementProperty();
        if (!propPlc) {
            continue;
        }
        savePair.second = propPlc->getValue();

        previousPositions.push_back(savePair);
    }
}

void AssemblyObject::undoSolve()
{
    if (previousPositions.size() == 0) {
        return;
    }

    for (auto& pair : previousPositions) {
        App::DocumentObject* obj = pair.first;
        if (!obj) {
            continue;
        }

        // Check if the object has a "Placement" property
        auto* propPlacement = obj->getPlacementProperty();
        if (!propPlacement) {
            continue;
        }

        propPlacement->setValue(pair.second);
    }
    previousPositions.clear();

    // update joint placements:
    getJoints(/*updateJCS*/ true, /*delBadJoints*/ false);
    getForces(/*updateJCS*/ true, /*delBadForces*/ false);
}

void AssemblyObject::clearUndo()
{
    previousPositions.clear();
}

void AssemblyObject::exportAsASMT(std::string fileName)
{
    mbdAssembly = makeMbdAssembly();
    objectPartMap.clear();
    objectJointMap.clear();
    fixGroundedParts();

    std::vector<App::DocumentObject*> joints = getJoints();

    jointParts(joints);

    std::vector<App::DocumentObject*> forces = getForces();
    forceParts(forces);

    mbdAssembly->outputFile(fileName);
}

void AssemblyObject::setNewPlacements()
{
    for (auto& pair : objectPartMap) {
        App::DocumentObject* obj = pair.first;
        std::shared_ptr<ASMTPart> mbdPart = pair.second.part;

        if (!obj || !mbdPart) {
            continue;
        }

        // Check if the object has a "Placement" property
        auto* propPlacement = obj->getPlacementProperty();
        if (!propPlacement) {
            continue;
        }


        Base::Placement newPlacement = getMbdPlacement(mbdPart);
        if (!pair.second.offsetPlc.isIdentity()) {
            newPlacement = newPlacement * pair.second.offsetPlc;
        }
        // JMW can get accel3d etc
        if (!propPlacement->getValue().isSame(newPlacement)) {
            propPlacement->setValue(newPlacement);
            obj->purgeTouched();
        }

        // std::vector<App::DocumentObject*> joints = getJointsOfPart(obj);
        // std::cout << "  part: " << obj->getFullName() << std::endl;
        // for (auto joint : joints) {
        //     std::cout << "    joint: " << joint->getFullName() << std::endl;
        // }
    }
}

void AssemblyObject::redrawJointPlacements(std::vector<App::DocumentObject*> joints)
{
    // Notify the joint objects that the transform of the coin object changed.
    for (auto* joint : joints) {
        if (!joint) {
            continue;
        }
        redrawJointPlacement(joint);
    }
}

void AssemblyObject::redrawJointPlacement(App::DocumentObject* joint)
{
    if (!joint) {
        return;
    }

    Base::PyGILStateLocker lock;

    App::PropertyPythonObject* proxy = joint
        ? dynamic_cast<App::PropertyPythonObject*>(joint->getPropertyByName("Proxy"))
        : nullptr;

    if (!proxy) {
        return;
    }

    Py::Object jointPy = proxy->getValue();

    if (!jointPy.hasAttr("redrawJointPlacements")) {
        return;
    }

    Py::Object attr = jointPy.getAttr("redrawJointPlacements");
    if (attr.ptr() && attr.isCallable()) {
        Py::Tuple args(1);
        args.setItem(0, Py::asObject(joint->getPyObject()));
        Py::Callable(attr).apply(args);
    }
}

std::shared_ptr<ASMTAssembly> AssemblyObject::makeMbdAssembly()
{
    auto assembly = ASMTAssembly::With();
    assembly->setName("OndselAssembly");

    ParameterGrp::handle hPgr = App::GetApplication().GetParameterGroupByPath(
        "User parameter:BaseApp/Preferences/Mod/Assembly"
    );

    return assembly;
}

App::DocumentObject* AssemblyObject::getJointOfPartConnectingToGround(
    App::DocumentObject* part,
    std::string& name,
    const std::vector<App::DocumentObject*>& excludeJoints
)
{
    if (!part) {
        return nullptr;
    }

    std::vector<App::DocumentObject*> joints = getJointsOfPart(part);

    for (auto joint : joints) {
        if (!joint) {
            continue;
        }

        if (std::ranges::find(excludeJoints, joint) != excludeJoints.end()) {
            continue;
        }

        App::DocumentObject* part1 = getMovingPartFromRef(joint, "Reference1");
        App::DocumentObject* part2 = getMovingPartFromRef(joint, "Reference2");
        if (!part1 || !part2) {
            continue;
        }

        if (part == part1 && isJointConnectingPartToGround(joint, "Reference1")) {
            name = "Reference1";
            return joint;
        }
        if (part == part2 && isJointConnectingPartToGround(joint, "Reference2")) {
            name = "Reference2";
            return joint;
        }
    }
    return nullptr;
}

template<typename T>
T* AssemblyObject::getGroup()
{
    App::Document* doc = getDocument();

    std::vector<DocumentObject*> groups = doc->getObjectsOfType(T::getClassTypeId());
    if (groups.empty()) {
        return nullptr;
    }
    for (auto group : groups) {
        if (hasObject(group)) {
            return freecad_cast<T*>(group);
        }
    }
    return nullptr;
}

JointGroup* AssemblyObject::getJointGroup() const
{
    return Assembly::getJointGroup(this);
}

ForceGroup* AssemblyObject::getForceGroup() const
{
    return Assembly::getForceGroup(this);
}

ViewGroup* AssemblyObject::getExplodedViewGroup() const
{
    App::Document* doc = getDocument();

    std::vector<DocumentObject*> viewGroups = doc->getObjectsOfType(ViewGroup::getClassTypeId());
    if (viewGroups.empty()) {
        return nullptr;
    }
    for (auto viewGroup : viewGroups) {
        if (hasObject(viewGroup)) {
            return freecad_cast<ViewGroup*>(viewGroup);
        }
    }
    return nullptr;
}

std::vector<App::DocumentObject*> AssemblyObject::getForces(bool updateJCS, bool delBadForces)
{
    std::vector<App::DocumentObject*> forces = {};

    ForceGroup* forceGroup = getForceGroup();
    if (!forceGroup) {
        // std::cerr << "No ForceGroup found in Assembly" << std::endl << std::flush;
        return {};
    }

    Base::PyGILStateLocker lock;
    for (auto force : forceGroup->getObjects()) {
        if (!force) {
            continue;
        }

        auto* prop = dynamic_cast<App::PropertyBool*>(force->getPropertyByName("Suppressed"));
        if (force->isError() || !prop || prop->getValue()) {
            // Filter grounded forces and deactivated forces.
            std::cerr << "Removing bad force 1 " << force->getFullName() << std::endl << std::flush;
            if (delBadForces) {
                getDocument()->removeObject(force->getNameInDocument());
            }
            continue;
        }

        auto* part1 = getMovingPartFromRef(force, "Reference1");
        auto* part2 = getMovingPartFromRef(force, "Reference2");
        if (!part1 || !part2 || part1->getFullName() == part2->getFullName()) {
            // Remove incomplete forces. Left-over when the user deletes a part.
            // Remove incoherent forces (self-pointing forces)
            std::cerr << "Removing bad force 2 " << force->getFullName() << std::endl << std::flush;
            if (delBadForces) {
                getDocument()->removeObject(force->getNameInDocument());
            }
            continue;
        }

        forces.push_back(force);
    }

    // Make sure the forces are up to date.
    if (updateJCS) {
        redrawJointPlacements(forces);
    }

    return forces;
}


std::vector<App::DocumentObject*> AssemblyObject::getJoints(bool updateJCS, bool delBadJoints, bool subJoints)
{
    std::vector<App::DocumentObject*> joints = {};

    JointGroup* jointGroup = getJointGroup();
    if (!jointGroup) {
        return {};
    }

    Base::PyGILStateLocker lock;
    for (auto joint : jointGroup->getObjects()) {
        if (!joint) {
            continue;
        }

        auto* prop = dynamic_cast<App::PropertyBool*>(joint->getPropertyByName("Suppressed"));
        if (joint->isError() || !prop || prop->getValue()) {
            // Filter grounded joints and deactivated joints.
            continue;
        }

        auto* part1 = getMovingPartFromRef(joint, "Reference1");
        auto* part2 = getMovingPartFromRef(joint, "Reference2");
        if (!part1 || !part2 || part1->getFullName() == part2->getFullName()) {
            // Remove incomplete joints. Left-over when the user deletes a part.
            // Remove incoherent joints (self-pointing joints)
            if (delBadJoints) {
                getDocument()->removeObject(joint->getNameInDocument());
            }
            continue;
        }

        auto proxy = dynamic_cast<App::PropertyPythonObject*>(joint->getPropertyByName("Proxy"));
        if (proxy) {
            if (proxy->getValue().hasAttr("setJointConnectors")) {
                joints.push_back(joint);
            }
        }
    }

    // add sub assemblies joints.
    if (subJoints) {
        for (auto& assembly : getSubAssemblies()) {
            auto subJoints = assembly->getJoints();
            joints.insert(joints.end(), subJoints.begin(), subJoints.end());
        }
    }

    if (updateJCS) {
        redrawJointPlacements(joints);
    }

    return joints;
}

std::vector<App::DocumentObject*> AssemblyObject::getGroundedJoints()
{
    std::vector<App::DocumentObject*> joints = {};

    JointGroup* jointGroup = getJointGroup();
    if (!jointGroup) {
        return {};
    }

    Base::PyGILStateLocker lock;
    for (auto obj : jointGroup->getObjects()) {
        if (!obj) {
            continue;
        }

        auto* propObj = dynamic_cast<App::PropertyLink*>(obj->getPropertyByName("ObjectToGround"));

        if (propObj) {
            joints.push_back(obj);
        }
    }

    return joints;
}

std::vector<App::DocumentObject*> AssemblyObject::getJointsOfObj(App::DocumentObject* obj)
{
    if (!obj) {
        return {};
    }

    std::vector<App::DocumentObject*> joints = getJoints();
    std::vector<App::DocumentObject*> jointsOf;

    for (auto joint : joints) {
        App::DocumentObject* obj1 = getObjFromJointRef(joint, "Reference1");
        App::DocumentObject* obj2 = getObjFromJointRef(joint, "Reference2");
        if (obj == obj1 || obj == obj2) {
            jointsOf.push_back(joint);
        }
    }

    return jointsOf;
}

std::vector<App::DocumentObject*> AssemblyObject::getJointsOfPart(App::DocumentObject* part)
{
    if (!part) {
        return {};
    }

    std::vector<App::DocumentObject*> joints = getJoints();
    std::vector<App::DocumentObject*> jointsOf;

    for (auto joint : joints) {
        App::DocumentObject* part1 = getMovingPartFromRef(joint, "Reference1");
        App::DocumentObject* part2 = getMovingPartFromRef(joint, "Reference2");
        if (part == part1 || part == part2) {
            jointsOf.push_back(joint);
        }
    }
    return jointsOf;
}

std::unordered_set<App::DocumentObject*> AssemblyObject::getGroundedParts()
{
    std::unordered_set<App::DocumentObject*> groundedSet;
    std::vector<App::DocumentObject*> allParts = getAssemblyComponents(this);
    for (auto part : allParts) {
        if (part) {
            auto propPlc = part->getPlacementProperty();
            if (propPlc && propPlc->isReadOnly()) {
                groundedSet.insert(part);
            }
        }
    }

    // We also need to add all the root-level datums objects that are not attached.
    std::vector<App::DocumentObject*> objs = Group.getValues();
    for (auto* obj : objs) {
        if (obj->isDerivedFrom<App::LocalCoordinateSystem>()
            || obj->isDerivedFrom<App::DatumElement>()) {
            auto* pcAttach = obj->getExtensionByType<PartApp::AttachExtension>();
            if (pcAttach) {
                // If it's a Part datums, we check if it's attached. If yes then we ignore it.
                std::string mode = pcAttach->MapMode.getValueAsString();
                if (mode != "Deactivated") {
                    continue;
                }
            }
            groundedSet.insert(obj);
        }
    }

    // Origin is not in Group so we add it separately
    groundedSet.insert(Origin.getValue());

    return groundedSet;
}

std::unordered_set<App::DocumentObject*> AssemblyObject::fixGroundedParts()
{
    auto groundedParts = getGroundedParts();

    for (auto obj : groundedParts) {
        if (!obj) {
            continue;
        }

        Base::Placement plc = getPlacementFromProp(obj, "Placement");
        std::string str = obj->getFullName();
        fixGroundedPart(obj, plc, str);
    }
    return groundedParts;
}

void AssemblyObject::fixGroundedPart(App::DocumentObject* obj, Base::Placement& plc, std::string& name)
{
    if (!obj) {
        return;
    }

    std::string markerName1 = "marker-" + obj->getFullName();
    auto mbdMarker1 = makeMbdMarker(markerName1, plc);
    mbdAssembly->addMarker(mbdMarker1);

    std::shared_ptr<ASMTPart> mbdPart = getMbDPart(obj);

    std::string markerName2 = "FixingMarker";
    Base::Placement basePlc = Base::Placement();
    auto mbdMarker2 = makeMbdMarker(markerName2, basePlc);
    mbdPart->addMarker(mbdMarker2);

    markerName1 = "/OndselAssembly/" + mbdMarker1->name;
    markerName2 = "/OndselAssembly/" + mbdPart->name + "/" + mbdMarker2->name;

    auto mbdJoint = ASMTFixedJoint::With();
    mbdJoint->setName(name);
    setMarkerICompat(mbdJoint, mbdMarker1);
    setMarkerJCompat(mbdJoint, mbdMarker2);

    mbdAssembly->addJoint(mbdJoint);
    addObjectsToJointMap(mbdJoint, obj);
}

void AssemblyObject::addObjectsToJointMap(
    std::shared_ptr<MbD::ASMTItemIJ> mbdJoint,
    App::DocumentObject* joint
)
{
    MbDJointData data = {mbdJoint};
    objectJointMap[joint] = data;  // Store the association
}

bool AssemblyObject::isJointConnectingPartToGround(App::DocumentObject* joint, const char* propname)
{
    if (!joint || !isJointTypeConnecting(joint)) {
        return false;
    }

    App::DocumentObject* part = getMovingPartFromRef(joint, propname);
    if (!part) {
        return false;
    }

    // Check if the part is grounded.
    bool isGrounded = isPartGrounded(part);
    if (isGrounded) {
        return false;
    }

    // Check if the part is disconnected even with the joint
    bool isConnected = isPartConnected(part);
    if (!isConnected) {
        return false;
    }

    // to know if a joint is connecting to ground we disable all the other joints
    std::vector<App::DocumentObject*> jointsOfPart = getJointsOfPart(part);
    std::vector<bool> activatedStates;

    for (auto jointi : jointsOfPart) {
        if (jointi->getFullName() == joint->getFullName()) {
            continue;
        }

        activatedStates.push_back(getJointActivated(jointi));
        setJointActivated(jointi, false);
    }

    isConnected = isPartConnected(part);

    // restore activation states
    for (auto jointi : jointsOfPart) {
        if (jointi->getFullName() == joint->getFullName() || activatedStates.empty()) {
            continue;
        }

        setJointActivated(jointi, activatedStates[0]);
        activatedStates.erase(activatedStates.begin());
    }

    return isConnected;
}

bool AssemblyObject::isJointTypeConnecting(App::DocumentObject* joint)
{
    if (!joint) {
        return false;
    }

    JointType jointType = getJointType(joint);
    return jointType != JointType::RackPinion && jointType != JointType::Screw
        && jointType != JointType::Gears && jointType != JointType::Belt;
}


bool AssemblyObject::isObjInSetOfObjRefs(App::DocumentObject* obj, const std::vector<ObjRef>& set)
{
    if (!obj) {
        return false;
    }

    for (const auto& pair : set) {
        if (pair.obj == obj) {
            return true;
        }
    }
    return false;
}

void AssemblyObject::removeUnconnectedJoints(
    std::vector<App::DocumentObject*>& joints,
    std::unordered_set<App::DocumentObject*> groundedObjs
)
{
    std::vector<ObjRef> connectedParts;

    // Initialize connectedParts with groundedObjs
    for (auto* groundedObj : groundedObjs) {
        connectedParts.push_back({groundedObj, nullptr});
    }

    // Perform a traversal from each grounded object
    for (auto* groundedObj : groundedObjs) {
        traverseAndMarkConnectedParts(groundedObj, connectedParts, joints);
    }

    // Filter out unconnected joints
    joints.erase(
        std::remove_if(
            joints.begin(),
            joints.end(),
            [&](App::DocumentObject* joint) {
                App::DocumentObject* obj1 = getMovingPartFromRef(joint, "Reference1");
                App::DocumentObject* obj2 = getMovingPartFromRef(joint, "Reference2");
                return (
                    !isObjInSetOfObjRefs(obj1, connectedParts)
                    || !isObjInSetOfObjRefs(obj2, connectedParts)
                );
            }
        ),
        joints.end()
    );
}

void AssemblyObject::traverseAndMarkConnectedParts(
    App::DocumentObject* currentObj,
    std::vector<ObjRef>& connectedParts,
    const std::vector<App::DocumentObject*>& joints
)
{
    // getConnectedParts returns the objs connected to the currentObj by any joint
    auto connectedObjs = getConnectedParts(currentObj, joints);
    for (auto& nextObjRef : connectedObjs) {
        if (!isObjInSetOfObjRefs(nextObjRef.obj, connectedParts)) {
            // Create a new ObjRef with the nextObj and a nullptr for PropertyXLinkSub*
            connectedParts.push_back(nextObjRef);
            traverseAndMarkConnectedParts(nextObjRef.obj, connectedParts, joints);
        }
    }
}

std::vector<ObjRef> AssemblyObject::getConnectedParts(
    App::DocumentObject* part,
    const std::vector<App::DocumentObject*>& joints
)
{
    if (!part) {
        return {};
    }

    std::vector<ObjRef> connectedParts;

    for (auto joint : joints) {
        if (!isJointTypeConnecting(joint)) {
            continue;
        }

        App::DocumentObject* obj1 = getMovingPartFromRef(joint, "Reference1");
        App::DocumentObject* obj2 = getMovingPartFromRef(joint, "Reference2");

        if (!obj1 || !obj2) {
            continue;
        }

        if (obj1 == part) {
            auto* ref = dynamic_cast<App::PropertyXLinkSub*>(joint->getPropertyByName("Reference2"));
            if (!ref) {
                continue;
            }
            connectedParts.push_back({obj2, ref});
        }
        else if (obj2 == part) {
            auto* ref = dynamic_cast<App::PropertyXLinkSub*>(joint->getPropertyByName("Reference1"));
            if (!ref) {
                continue;
            }
            connectedParts.push_back({obj1, ref});
        }
    }
    return connectedParts;
}

bool AssemblyObject::isPartGrounded(App::DocumentObject* obj)
{
    if (!obj) {
        return false;
    }

    auto groundedObjs = getGroundedParts();

    for (auto* groundedObj : groundedObjs) {
        if (groundedObj->getFullName() == obj->getFullName()) {
            return true;
        }
    }

    return false;
}

bool AssemblyObject::isPartConnected(App::DocumentObject* obj)
{
    if (!obj) {
        return false;
    }

    auto groundedObjs = getGroundedParts();
    std::vector<App::DocumentObject*> joints = getJoints();

    std::vector<ObjRef> connectedParts;

    // Initialize connectedParts with groundedObjs
    for (auto* groundedObj : groundedObjs) {
        connectedParts.push_back({groundedObj, nullptr});
    }

    // Perform a traversal from each grounded object
    for (auto* groundedObj : groundedObjs) {
        traverseAndMarkConnectedParts(groundedObj, connectedParts, joints);
    }

    for (auto& objRef : connectedParts) {
        if (obj == objRef.obj) {
            return true;
        }
    }

    return false;
}


void AssemblyObject::forceParts(std::vector<App::DocumentObject*> forces)
{
    for (auto* force : forces) {
        if (!force) {
            continue;
        }

        std::vector<std::shared_ptr<MbD::ASMTForceTorque>> mbdForceTorques = makeMbdForceTorque(force);
        for (auto& mbdForceTorque : mbdForceTorques) {
            mbdAssembly->addForceTorque(mbdForceTorque);
            // TODO JMW
            addObjectsToJointMap(mbdForceTorque, force);
            std::cout << "Added force/torque " << mbdForceTorque->name << std::endl;
            std::cout << std::flush;
        }
    }
}

void AssemblyObject::jointParts(std::vector<App::DocumentObject*> joints)
{
    for (auto* joint : joints) {
        if (!joint) {
            continue;
        }

        std::vector<std::shared_ptr<MbD::ASMTJoint>> mbdJoints = makeMbdJoint(joint);
        for (auto& mbdJoint : mbdJoints) {
            mbdAssembly->addJoint(mbdJoint);
            addObjectsToJointMap(mbdJoint, joint);
        }
    }
}


void Assembly::AssemblyObject::create_mbdSimulationParameters(App::DocumentObject* sim)
{
    auto mbdSim = mbdAssembly->simulationParameters;
    if (!sim) {
        return;
    }
    auto valueOf = [](DocumentObject* docObj, const char* propName) {
        auto* prop = dynamic_cast<App::PropertyFloat*>(docObj->getPropertyByName(propName));
        if (!prop) {
            return 0.0;
        }
        return prop->getValue();
    };
    mbdSim->settstart(valueOf(sim, "aTimeStart"));
    mbdSim->settend(valueOf(sim, "bTimeEnd"));
    mbdSim->sethout(valueOf(sim, "cTimeStepOutput"));
    mbdSim->sethmin(1.0e-9);
    mbdSim->sethmax(1.0);
    mbdSim->seterrorTol(valueOf(sim, "fGlobalErrorTolerance"));
}

std::shared_ptr<ASMTJoint> AssemblyObject::makeMbdJointOfType(App::DocumentObject* joint, JointType type)
{
    switch (type) {
        case JointType::Fixed:
            if (bundleFixed) {
                return nullptr;
            }
            return ASMTFixedJoint::With();

        case JointType::Revolute:
            return ASMTRevoluteJoint::With();

        case JointType::Cylindrical:
            return ASMTCylindricalJoint::With();

        case JointType::Slider:
            return ASMTTranslationalJoint::With();

        case JointType::Ball:
            return ASMTSphericalJoint::With();

        case JointType::Distance:
            return makeMbdJointDistance(joint);

        case JointType::Parallel:
            return ASMTParallelAxesJoint::With();

        case JointType::Perpendicular:
            return ASMTPerpendicularJoint::With();

        case JointType::Angle: {
            double angle = fabs(Base::toRadians(getJointAngle(joint)));
            if (fmod(angle, 2 * std::numbers::pi) < Precision::Confusion()) {
                return ASMTParallelAxesJoint::With();
            }
            auto mbdJoint = ASMTAngleJoint::With();
            mbdJoint->theIzJz = angle;
            return mbdJoint;
        }

        case JointType::RackPinion: {
            auto mbdJoint = ASMTRackPinionJoint::With();
            mbdJoint->pitchRadius = getJointDistance(joint);
            return mbdJoint;
        }

        case JointType::Screw: {
            int slidingIndex = slidingPartIndex(joint);
            if (slidingIndex == 0) {  // invalid this joint needs a slider
                return nullptr;
            }

            if (slidingIndex != 1) {
                swapJCS(joint);  // make sure that sliding is first.
            }

            auto mbdJoint = ASMTScrewJoint::With();
            mbdJoint->pitch = getJointDistance(joint);
            return mbdJoint;
        }

        case JointType::Gears: {
            auto mbdJoint = ASMTGearJoint::With();
            mbdJoint->radiusI = getJointDistance(joint);
            mbdJoint->radiusJ = getJointDistance2(joint);
            return mbdJoint;
        }

        case JointType::Belt: {
            auto mbdJoint = ASMTGearJoint::With();
            mbdJoint->radiusI = getJointDistance(joint);
            mbdJoint->radiusJ = -getJointDistance2(joint);
            return mbdJoint;
        }

        default:
            return nullptr;
    }
}

std::shared_ptr<ASMTJoint> AssemblyObject::makeMbdJointDistance(App::DocumentObject* joint)
{
    DistanceType type = getDistanceType(joint);

    std::string elt1 = getElementFromProp(joint, "Reference1");
    std::string elt2 = getElementFromProp(joint, "Reference2");
    auto* obj1 = getLinkedObjFromRef(joint, "Reference1");
    auto* obj2 = getLinkedObjFromRef(joint, "Reference2");

    switch (type) {
        case DistanceType::PointPoint: {
            // Point to point distance, or ball joint if distance=0.
            double distance = getJointDistance(joint);
            if (distance < Precision::Confusion()) {
                return ASMTSphericalJoint::With();
            }
            auto mbdJoint = ASMTSphSphJoint::With();
            mbdJoint->distanceIJ = distance;
            return mbdJoint;
        }

        // Edge - edge cases
        case DistanceType::LineLine: {
            auto mbdJoint = ASMTRevCylJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint);
            return mbdJoint;
        }

        case DistanceType::LineCircle: {
            auto mbdJoint = ASMTRevCylJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getEdgeRadius(obj2, elt2);
            return mbdJoint;
        }

        case DistanceType::CircleCircle: {
            auto mbdJoint = ASMTRevCylJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getEdgeRadius(obj1, elt1)
                + getEdgeRadius(obj2, elt2);
            return mbdJoint;
        }

        // Face - Face cases
        case DistanceType::PlanePlane: {
            auto mbdJoint = ASMTPlanarJoint::With();
            mbdJoint->offset = getJointDistance(joint);
            return mbdJoint;
        }

        case DistanceType::PlaneCylinder: {
            auto mbdJoint = ASMTLineInPlaneJoint::With();
            mbdJoint->offset = getJointDistance(joint) + getFaceRadius(obj2, elt2);
            return mbdJoint;
        }

        case DistanceType::PlaneSphere: {
            auto mbdJoint = ASMTPointInPlaneJoint::With();
            mbdJoint->offset = getJointDistance(joint) + getFaceRadius(obj2, elt2);
            return mbdJoint;
        }

        case DistanceType::PlaneTorus: {
            auto mbdJoint = ASMTPlanarJoint::With();
            mbdJoint->offset = getJointDistance(joint);
            return mbdJoint;
        }

        case DistanceType::CylinderCylinder: {
            auto mbdJoint = ASMTRevCylJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getFaceRadius(obj1, elt1)
                + getFaceRadius(obj2, elt2);
            return mbdJoint;
        }

        case DistanceType::CylinderSphere: {
            auto mbdJoint = ASMTCylSphJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getFaceRadius(obj1, elt1)
                + getFaceRadius(obj2, elt2);
            return mbdJoint;
        }

        case DistanceType::CylinderTorus: {
            auto mbdJoint = ASMTRevCylJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getFaceRadius(obj1, elt1)
                + getFaceRadius(obj2, elt2);
            return mbdJoint;
        }

        case DistanceType::TorusTorus: {
            auto mbdJoint = ASMTPlanarJoint::With();
            mbdJoint->offset = getJointDistance(joint);
            return mbdJoint;
        }

        case DistanceType::TorusSphere: {
            auto mbdJoint = ASMTCylSphJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getFaceRadius(obj1, elt1)
                + getFaceRadius(obj2, elt2);
            return mbdJoint;
        }

        case DistanceType::SphereSphere: {
            auto mbdJoint = ASMTSphSphJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getFaceRadius(obj1, elt1)
                + getFaceRadius(obj2, elt2);
            return mbdJoint;
        }

        // Point - Face cases
        case DistanceType::PointPlane: {
            auto mbdJoint = ASMTPointInPlaneJoint::With();
            mbdJoint->offset = getJointDistance(joint);
            return mbdJoint;
        }

        case DistanceType::PointCylinder: {
            auto mbdJoint = ASMTCylSphJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getFaceRadius(obj1, elt1);
            return mbdJoint;
        }

        case DistanceType::PointSphere: {
            auto mbdJoint = ASMTSphSphJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint) + getFaceRadius(obj1, elt1);
            return mbdJoint;
        }

        // Edge - Face cases
        case DistanceType::LinePlane: {
            auto mbdJoint = ASMTLineInPlaneJoint::With();
            mbdJoint->offset = getJointDistance(joint);
            return mbdJoint;
        }

        // Point - Edge cases
        case DistanceType::PointLine: {
            auto mbdJoint = ASMTCylSphJoint::With();
            mbdJoint->distanceIJ = getJointDistance(joint);
            return mbdJoint;
        }

        case DistanceType::PointCurve: {
            // For other curves we do a point in plane-of-the-curve.
            // Maybe it would be best tangent / distance to the conic?
            // For arcs and circles we could use ASMTRevSphJoint. But is it better than
            // pointInPlane?
            auto mbdJoint = ASMTPointInPlaneJoint::With();
            mbdJoint->offset = getJointDistance(joint);
            return mbdJoint;
        }

        default: {
            // by default we make a planar joint.
            auto mbdJoint = ASMTPlanarJoint::With();
            mbdJoint->offset = getJointDistance(joint);
            return mbdJoint;
        }
    }
}


std::shared_ptr<MbD::ASMTForceTorque> AssemblyObject::makeMbdForceTorqueOfType(
    App::DocumentObject* force,
    const ForceType forceType
)
{
    // TODO JMW check validity of the force here
    switch (forceType) {
        case ForceType::General: {
            std::shared_ptr<ASMTForceTorqueGeneral> mbdForceTorque = ASMTForceTorqueGeneral::With();
            mbdForceTorque->aFIeKe->atiput(0, getForceFunction(force, "ForceX"));
            mbdForceTorque->aFIeKe->atiput(1, getForceFunction(force, "ForceY"));
            mbdForceTorque->aFIeKe->atiput(2, getForceFunction(force, "ForceZ"));
            mbdForceTorque->aTIeKe->atiput(0, getForceFunction(force, "TorqueX"));
            mbdForceTorque->aTIeKe->atiput(1, getForceFunction(force, "TorqueY"));
            mbdForceTorque->aTIeKe->atiput(2, getForceFunction(force, "TorqueZ"));
            const auto markerKSign = getForceMarkerKSign(force);
            switch (markerKSign) {
                case MarkerKSign::I:
                    mbdForceTorque->markerKSign = "I";
                    break;
                case MarkerKSign::J:
                    mbdForceTorque->markerKSign = "J";
                    break;
                default:
                    mbdForceTorque->markerKSign = "O";
            }
            return mbdForceTorque;
        } break;
        case ForceType::InLine: {
            std::shared_ptr<ASMTForceTorqueInLine> mbdForceTorque = ASMTForceTorqueInLine::With();
            mbdForceTorque->tensionFunc = getForceFunction(force, "Tension");
            mbdForceTorque->twistFunc = getForceFunction(force, "Twist");
            return mbdForceTorque;
        } break;
        default:
            std::cerr << "Unsupported force type for force " << force->getFullName() << std::endl;
            std::cerr << std::flush;
            return nullptr;
    }
}

std::vector<std::shared_ptr<MbD::ASMTForceTorque>> AssemblyObject::makeMbdForceTorque(
    App::DocumentObject* force
)
{
    if (!force) {
        return {};
    }

    const ForceType forceType = getForceType(force);
    std::shared_ptr<ASMTForceTorque> mbdForceTorque = makeMbdForceTorqueOfType(force, forceType);

    if (!mbdForceTorque) {
        return {};
    }

    marker_pair markers;
    markers.first = handleOneSideOfJoint(force, "Reference1", "Placement1");
    markers.second = handleOneSideOfJoint(force, "Reference2", "Placement2");
    if ((markers.first == nullptr) || (markers.second == nullptr)) {
        std::cerr << "Could not get markers for force " << force->getFullName() << std::endl;
        std::cerr << std::flush;
        return {};
    }

    mbdForceTorque->setName(force->getFullName());
    mbdForceTorque->setLabel(force->getFullLabel());
    setMarkerICompat(mbdForceTorque, markers.first);
    setMarkerJCompat(mbdForceTorque, markers.second);
    return {mbdForceTorque};
}


std::vector<std::shared_ptr<MbD::ASMTJoint>> AssemblyObject::makeMbdJoint(App::DocumentObject* joint)
{
    if (!joint) {
        return {};
    }

    JointType jointType = getJointType(joint);

    std::shared_ptr<ASMTJoint> mbdJoint = makeMbdJointOfType(joint, jointType);
    if (!mbdJoint || !isMbDJointValid(joint)) {
        return {};
    }

    marker_pair markers;
    if (jointType == JointType::RackPinion) {
        markers = getRackPinionMarkers(joint);
    }
    else {
        markers.first = handleOneSideOfJoint(joint, "Reference1", "Placement1");
        markers.second = handleOneSideOfJoint(joint, "Reference2", "Placement2");
    }
    if ((markers.first == nullptr) || (markers.second == nullptr)) {
        return {};
    }

    mbdJoint->setName(joint->getFullName());
    mbdJoint->setLabel(joint->getFullLabel());
    setMarkerICompat(mbdJoint, markers.first);
    setMarkerJCompat(mbdJoint, markers.second);

    // Add limits if needed. We do not add if this is a simulation or their might clash.
    if (motions.empty()) {
        if (jointType == JointType::Slider || jointType == JointType::Cylindrical) {
            auto* pLenMin = dynamic_cast<App::PropertyFloat*>(joint->getPropertyByName("LengthMin"));
            auto* pLenMax = dynamic_cast<App::PropertyFloat*>(joint->getPropertyByName("LengthMax"));
            auto* pMinEnabled = dynamic_cast<App::PropertyBool*>(
                joint->getPropertyByName("EnableLengthMin")
            );
            auto* pMaxEnabled = dynamic_cast<App::PropertyBool*>(
                joint->getPropertyByName("EnableLengthMax")
            );

            if (pLenMin && pLenMax && pMinEnabled && pMaxEnabled) {  // Make sure properties do exist
                // Swap the values if necessary.
                bool minEnabled = pMinEnabled->getValue();
                bool maxEnabled = pMaxEnabled->getValue();
                double minLength = pLenMin->getValue();
                double maxLength = pLenMax->getValue();

                if ((minLength > maxLength) && minEnabled && maxEnabled) {
                    pLenMin->setValue(maxLength);
                    pLenMax->setValue(minLength);
                    minLength = maxLength;
                    maxLength = pLenMax->getValue();

                    pMinEnabled->setValue(maxEnabled);
                    pMaxEnabled->setValue(minEnabled);
                    minEnabled = maxEnabled;
                    maxEnabled = pMaxEnabled->getValue();
                }

                if (minEnabled) {
                    auto limit = ASMTTranslationLimit::With();
                    limit->setName(joint->getFullName() + "-LimitLenMin");
                    setMarkerICompat(limit, markers.first);
                    setMarkerJCompat(limit, markers.second);
                    limit->settype("=>");
                    limit->setlimit(std::to_string(minLength));
                    limit->settol("1.0e-9");
                    mbdAssembly->addLimit(limit);
                }

                if (maxEnabled) {
                    auto limit2 = ASMTTranslationLimit::With();
                    limit2->setName(joint->getFullName() + "-LimitLenMax");
                    setMarkerICompat(limit2, markers.first);
                    setMarkerJCompat(limit2, markers.second);
                    limit2->settype("=<");
                    limit2->setlimit(std::to_string(maxLength));
                    limit2->settol("1.0e-9");
                    mbdAssembly->addLimit(limit2);
                }
            }
        }
        if (jointType == JointType::Revolute || jointType == JointType::Cylindrical) {
            auto* pRotMin = dynamic_cast<App::PropertyFloat*>(joint->getPropertyByName("AngleMin"));
            auto* pRotMax = dynamic_cast<App::PropertyFloat*>(joint->getPropertyByName("AngleMax"));
            auto* pMinEnabled = dynamic_cast<App::PropertyBool*>(
                joint->getPropertyByName("EnableAngleMin")
            );
            auto* pMaxEnabled = dynamic_cast<App::PropertyBool*>(
                joint->getPropertyByName("EnableAngleMax")
            );

            if (pRotMin && pRotMax && pMinEnabled && pMaxEnabled) {  // Make sure properties do exist
                // Swap the values if necessary.
                bool minEnabled = pMinEnabled->getValue();
                bool maxEnabled = pMaxEnabled->getValue();
                double minAngle = pRotMin->getValue();
                double maxAngle = pRotMax->getValue();
                if ((minAngle > maxAngle) && minEnabled && maxEnabled) {
                    pRotMin->setValue(maxAngle);
                    pRotMax->setValue(minAngle);
                    minAngle = maxAngle;
                    maxAngle = pRotMax->getValue();

                    pMinEnabled->setValue(maxEnabled);
                    pMaxEnabled->setValue(minEnabled);
                    minEnabled = maxEnabled;
                    maxEnabled = pMaxEnabled->getValue();
                }

                if (minEnabled) {
                    auto limit = ASMTRotationLimit::With();
                    limit->setName(joint->getFullName() + "-LimitRotMin");
                    setMarkerICompat(limit, markers.first);
                    setMarkerJCompat(limit, markers.second);
                    limit->settype("=>");
                    limit->setlimit(std::to_string(minAngle) + "*pi/180.0");
                    limit->settol("1.0e-9");
                    mbdAssembly->addLimit(limit);
                }

                if (maxEnabled) {
                    auto limit2 = ASMTRotationLimit::With();
                    limit2->setName(joint->getFullName() + "-LimitRotMax");
                    setMarkerICompat(limit2, markers.first);
                    setMarkerJCompat(limit2, markers.second);
                    limit2->settype("=<");
                    limit2->setlimit(std::to_string(maxAngle) + "*pi/180.0");
                    limit2->settol("1.0e-9");
                    mbdAssembly->addLimit(limit2);
                }
            }
        }
    }
    std::vector<App::DocumentObject*> done;

    auto replaceInitialValue =
        [](std::string& form, App::DocumentObject* jnt, const std::string& mType) {
            if (form.find("initialValue") != std::string::npos) {
                double val = getJointCurrentValue(jnt, mType == "Angular");

                std::ostringstream out;
                out.precision(10);
                out << val;
                std::string valStr = out.str();

                size_t pos;
                while ((pos = form.find("initialValue")) != std::string::npos) {
                    form.replace(pos, 12, valStr);
                }
            }
        };

    // Add motions if needed
    for (auto* motion : motions) {
        if (std::ranges::find(done, motion) != done.end()) {
            continue;  // don't process twice (can happen in case of cylindrical)
        }

        auto* pJoint = dynamic_cast<App::PropertyXLinkSub*>(motion->getPropertyByName("Joint"));
        if (!pJoint) {
            continue;
        }
        App::DocumentObject* motionJoint = pJoint->getValue();
        if (joint != motionJoint) {
            continue;
        }

        auto* pType = dynamic_cast<App::PropertyEnumeration*>(motion->getPropertyByName("MotionType"));
        auto* pFormula = dynamic_cast<App::PropertyString*>(motion->getPropertyByName("Formula"));
        if (!pType || !pFormula) {
            continue;
        }
        std::string formula = pFormula->getValue();
        if (formula == "") {
            continue;
        }
        std::string motionType = pType->getValueAsString();

        replaceInitialValue(formula, joint, motionType);

        // check if there is a second motion as cylindrical can have both,
        // in which case the solver needs a general motion.
        for (auto* motion2 : motions) {
            pJoint = dynamic_cast<App::PropertyXLinkSub*>(motion2->getPropertyByName("Joint"));
            if (!pJoint) {
                continue;
            }
            motionJoint = pJoint->getValue();
            if (joint != motionJoint || motion2 == motion) {
                continue;
            }

            auto* pType2 = dynamic_cast<App::PropertyEnumeration*>(
                motion2->getPropertyByName("MotionType")
            );
            auto* pFormula2 = dynamic_cast<App::PropertyString*>(motion2->getPropertyByName("Formula"));
            if (!pType2 || !pFormula2) {
                continue;
            }
            std::string formula2 = pFormula2->getValue();
            if (formula2 == "") {
                continue;
            }
            std::string motionType2 = pType2->getValueAsString();
            if (motionType2 == motionType) {
                continue;  // only if both motions are different. ie one angular and one linear.
            }

            replaceInitialValue(formula2, joint, motionType2);

            auto ASMTmotion = ASMTGeneralMotion::With();
            ASMTmotion->setName(joint->getFullName() + "-ScrewMotion");
            setMarkerICompat(ASMTmotion, markers.first);
            setMarkerJCompat(ASMTmotion, markers.second);
            ASMTmotion->rIJI->atiput(2, motionType == "Angular" ? formula2 : formula);
            ASMTmotion->angIJJ->atiput(2, motionType == "Angular" ? formula : formula2);
            mbdAssembly->addMotion(ASMTmotion);
            done.push_back(motion2);
            addObjectsToJointMap(ASMTmotion, motion2);
        }

        if (motionType == "Angular") {
            auto ASMTmotion = ASMTRotationalMotion::With();
            ASMTmotion->setName(joint->getFullName() + "-AngularMotion");
            setMarkerICompat(ASMTmotion, markers.first);
            setMarkerJCompat(ASMTmotion, markers.second);
            ASMTmotion->setRotationZ(formula);
            mbdAssembly->addMotion(ASMTmotion);
            addObjectsToJointMap(ASMTmotion, motion);
        }
        else if (motionType == "Linear") {
            auto ASMTmotion = ASMTTranslationalMotion::With();
            ASMTmotion->setName(joint->getFullName() + "-LinearMotion");
            setMarkerICompat(ASMTmotion, markers.first);
            setMarkerJCompat(ASMTmotion, markers.second);
            ASMTmotion->translationZ = formula;
            mbdAssembly->addMotion(ASMTmotion);
            addObjectsToJointMap(ASMTmotion, motion);
        }
    }

    return {mbdJoint};
}

std::shared_ptr<ASMTMarker> AssemblyObject::handleOneSideOfJoint(
    App::DocumentObject* joint,
    const char* propRefName,
    const char* propPlcName
)
{
    App::DocumentObject* part = getMovingPartFromRef(joint, propRefName);
    App::DocumentObject* obj = getObjFromJointRef(joint, propRefName);

    if (!part || !obj) {
        Base::Console()
            .warning("The property %s of Joint %s is bad.\n", propRefName, joint->getFullName());
        return nullptr;
    }

    MbDPartData data = getMbDData(part);
    std::shared_ptr<ASMTPart> mbdPart = data.part;
    Base::Placement plc = getPlacementFromProp(joint, propPlcName);
    // Now we have plc which is the JCS placement, but its relative to the Object, not to the
    // containing Part.

    auto* ref = dynamic_cast<App::PropertyXLinkSub*>(joint->getPropertyByName(propRefName));

    if (obj->getNameInDocument() != part->getNameInDocument()) {

        if (!ref) {
            return nullptr;
        }

        Base::Placement obj_global_plc = getGlobalPlacement(obj, ref);
        plc = obj_global_plc * plc;

        Base::Placement part_global_plc = getGlobalPlacement(part, ref);
        plc = part_global_plc.inverse() * plc;
    }

    // This plc adjustment should be necessary only if obj != part. But for some objects like
    // draft links, we can have obj == part and still need to get global placement to adjust
    // by the element placement.
    Base::Placement obj_global_plc = getGlobalPlacement(nullptr, ref);
    plc = obj_global_plc * plc;
    // Note part is supposed to be root of ref, so we could use part.Placement directly.
    Base::Placement part_global_plc = getGlobalPlacement(part, ref);
    plc = part_global_plc.inverse() * plc;

    // check if we need to add an offset in case of bundled parts.
    if (!data.offsetPlc.isIdentity()) {
        plc = data.offsetPlc * plc;
    }

    std::string markerName = joint->getFullName();
    auto mbdMarker = makeMbdMarker(markerName, plc);
    mbdPart->addMarker(mbdMarker);

    return mbdMarker;
}

AssemblyObject::marker_pair AssemblyObject::getRackPinionMarkers(App::DocumentObject* joint)
{
    // ASMT rack pinion joint must get the rack as I and pinion as J.
    // - rack marker has to have Z axis parallel to pinion Z axis.
    // - rack marker has to have X axis parallel to the sliding axis.
    // The user will have selected the sliding marker so we need to transform it.
    // And we need to detect which marker is the rack.
    auto null_pair = marker_pair(nullptr, nullptr);

    int slidingIndex = slidingPartIndex(joint);
    if (slidingIndex == 0) {
        return null_pair;
    }

    if (slidingIndex != 1) {
        swapJCS(joint);  // make sure that rack is first.
    }

    App::DocumentObject* part1 = getMovingPartFromRef(joint, "Reference1");
    App::DocumentObject* obj1 = getObjFromJointRef(joint, "Reference1");
    Base::Placement plc1 = getPlacementFromProp(joint, "Placement1");

    App::DocumentObject* obj2 = getObjFromJointRef(joint, "Reference2");
    Base::Placement plc2 = getPlacementFromProp(joint, "Placement2");

    if (!part1 || !obj1) {
        Base::Console().warning("Reference1 of Joint %s is bad.\n", joint->getFullName());
        return null_pair;
    }

    // For the pinion nothing special needed :
    auto markerJ = handleOneSideOfJoint(joint, "Reference2", "Placement2");

    // For the rack we need to change the placement :
    // make the pinion plc relative to the rack placement.
    auto* ref1 = dynamic_cast<App::PropertyXLinkSub*>(joint->getPropertyByName("Reference1"));
    auto* ref2 = dynamic_cast<App::PropertyXLinkSub*>(joint->getPropertyByName("Reference2"));
    if (!ref1 || !ref2) {
        return null_pair;
    }
    Base::Placement pinion_global_plc = getGlobalPlacement(obj2, ref2);
    plc2 = pinion_global_plc * plc2;
    Base::Placement rack_global_plc = getGlobalPlacement(obj1, ref1);
    plc2 = rack_global_plc.inverse() * plc2;

    // The rot of the rack placement should be the same as the pinion, but with X axis along the
    // slider axis.
    Base::Rotation rot = plc2.getRotation();
    // the yaw of rot has to be the same as plc1
    Base::Vector3d currentZAxis = rot.multVec(Base::Vector3d(0, 0, 1));
    Base::Vector3d currentXAxis = rot.multVec(Base::Vector3d(1, 0, 0));
    Base::Vector3d targetXAxis = plc1.getRotation().multVec(Base::Vector3d(0, 0, 1));

    // Calculate the angle between the current X axis and the target X axis
    double yawAdjustment = currentXAxis.GetAngle(targetXAxis);

    // Determine the direction of the yaw adjustment using cross product
    Base::Vector3d crossProd = currentXAxis.Cross(targetXAxis);
    if (currentZAxis * crossProd < 0) {  // If cross product is in opposite direction to Z axis
        yawAdjustment = -yawAdjustment;
    }

    // Create a yaw rotation around the Z axis
    Base::Rotation yawRotation(currentZAxis, yawAdjustment);

    // Combine the initial rotation with the yaw adjustment
    Base::Rotation adjustedRotation = rot * yawRotation;
    plc1.setRotation(adjustedRotation);

    // Then end of processing similar to handleOneSideOfJoint :
    MbDPartData data1 = getMbDData(part1);
    std::shared_ptr<ASMTPart> mbdPart = data1.part;
    if (obj1->getNameInDocument() != part1->getNameInDocument()) {
        plc1 = rack_global_plc * plc1;

        Base::Placement part_global_plc = getGlobalPlacement(part1, ref1);
        plc1 = part_global_plc.inverse() * plc1;
    }
    // check if we need to add an offset in case of bundled parts.
    if (!data1.offsetPlc.isIdentity()) {
        plc1 = data1.offsetPlc * plc1;
    }

    std::string markerName = joint->getFullName();
    auto markerI = makeMbdMarker(markerName, plc1);
    mbdPart->addMarker(markerI);
    return marker_pair(markerI, markerJ);
}

int AssemblyObject::slidingPartIndex(App::DocumentObject* joint)
{
    App::DocumentObject* part1 = getMovingPartFromRef(joint, "Reference1");
    App::DocumentObject* obj1 = getObjFromJointRef(joint, "Reference1");
    boost::ignore_unused(obj1);
    Base::Placement plc1 = getPlacementFromProp(joint, "Placement1");

    App::DocumentObject* part2 = getMovingPartFromRef(joint, "Reference2");
    App::DocumentObject* obj2 = getObjFromJointRef(joint, "Reference2");
    boost::ignore_unused(obj2);
    Base::Placement plc2 = getPlacementFromProp(joint, "Placement2");

    int slidingFound = 0;
    for (auto* jt : getJoints()) {
        if (getJointType(jt) == JointType::Slider) {
            App::DocumentObject* jpart1 = getMovingPartFromRef(jt, "Reference1");
            App::DocumentObject* jpart2 = getMovingPartFromRef(jt, "Reference2");
            int found = 0;
            Base::Placement plcjt, plci;
            if (jpart1 == part1 || jpart1 == part2) {
                found = (jpart1 == part1) ? 1 : 2;
                plci = (jpart1 == part1) ? plc1 : plc2;
                plcjt = getPlacementFromProp(jt, "Placement1");
            }
            else if (jpart2 == part1 || jpart2 == part2) {
                found = (jpart2 == part1) ? 1 : 2;
                plci = (jpart2 == part1) ? plc1 : plc2;
                plcjt = getPlacementFromProp(jt, "Placement2");
            }

            if (found != 0) {
                // check the placements plcjt and (jcs1 or jcs2 depending on found value) Z axis
                // are colinear ie if their pitch and roll are the same.
                double y1, p1, r1, y2, p2, r2;
                plcjt.getRotation().getYawPitchRoll(y1, p1, r1);
                plci.getRotation().getYawPitchRoll(y2, p2, r2);
                if (fabs(p1 - p2) < Precision::Confusion() && fabs(r1 - r2) < Precision::Confusion()) {
                    slidingFound = found;
                }
            }
        }
    }
    return slidingFound;
}

bool AssemblyObject::isMbDJointValid(App::DocumentObject* joint)
{
    // When dragging a part, we are bundling fixed parts together.
    // This may lead to a conflicting joint that is self referencing a MbD part.
    // The solver crash when fed such a bad joint. So we make sure it does not happen.
    App::DocumentObject* part1 = getMovingPartFromRef(joint, "Reference1");
    App::DocumentObject* part2 = getMovingPartFromRef(joint, "Reference2");
    if (!part1 || !part2) {
        return false;
    }

    // If this joint is self-referential it must be ignored.
    if (getMbDPart(part1) == getMbDPart(part2)) {
        Base::Console().warning(
            "Assembly: Ignoring joint (%s) because its parts are connected by a fixed "
            "joint bundle. This joint is a conflicting or redundant constraint.\n",
            joint->getFullLabel()
        );
        return false;
    }
    return true;
}


AssemblyObject::MbDInertialData AssemblyObject::getMbDInertial(App::DocumentObject* part)
{
    MbDInertialData data;
    double density = 1.0e-9;
    App::DocumentObject* materialPart = part;
    bool hasShapeMaterialDensity = false;
    double shapeMaterialDensity = density;
    // const Base::Placement orig_plc = getPlacementFromProp(part, "Placement");

    if (part->isDerivedFrom(App::Link::getClassTypeId())) {
        auto* link = static_cast<const App::Link*>(part);
        if (auto* linked = link->getLinkedObject()) {
            materialPart = linked;
        }
    }

    if (auto propMaterial = dynamic_cast<Materials::PropertyMaterial*>(
            materialPart->getPropertyByName("ShapeMaterial")
        )) {
        auto& mat = propMaterial->getValue();
        try {
            Base::Quantity densityQuantity = mat.getPhysicalQuantity("Density");
            shapeMaterialDensity = densityQuantity.getValue() / 1000.0;  // kg/m^3 -> t/mm^3
            hasShapeMaterialDensity = true;
            // units = densityQuantity.getUnit().getString()
        }
        catch (const std::exception& e) {
            // std::cerr << "Error accessing Density as Quantity: " << e.what() << std::endl;
        }
    }

    if (auto femDensity = getFemMaterialDensityTonPerMm3(part, materialPart)) {
        density = *femDensity;
    }
    else if (hasShapeMaterialDensity) {
        density = shapeMaterialDensity;
    }
    else if (dynamic_cast<PartApp::Feature*>(materialPart)) {
        std::cout << "  No material specified" << std::endl;
        std::cout << std::flush;
    }
    if (part->isDerivedFrom(App::Link::getClassTypeId())) {
        part = static_cast<const App::Link*>(part)->getLinkedObject();
        if (!part) {
            return data;
        }
    }
    else if (part->isDerivedFrom<App::Part>()) {
        // || part->isDerivedFrom<App::DocumentObjectGroup>())
        // for (auto child : static_cast<App::Part*>(part)->getObjects()) {
        //     std::cout << "  child: " << child->getFullName() << std::endl;
        // }
    }

    // These measures are all relative to linked placement
    // need to transform from this to new placement
    auto* base = dynamic_cast<PartApp::Feature*>(part);
    if (!base) {
        return data;
    }
    const auto& shape = base->Shape.getShape();
    const Base::Placement plc = getPlacementFromProp(part, "Placement").inverse();
    try {
        const GProp_GProps gpr = Attacher::AttachEngine::getInertialPropsOfShape({&shape});

        //////////
        const gp_Pnt centerOfMass = gpr.CentreOfMass();
        const Base::Vector3d com = plc.toMatrix()
            * Base::Vector3d(centerOfMass.X(), centerOfMass.Y(), centerOfMass.Z());
        const GProp_PrincipalProps pr = gpr.PrincipalProperties();
        const gp_Vec ax1 = pr.FirstAxisOfInertia();
        const gp_Vec ax2 = pr.SecondAxisOfInertia();
        const gp_Vec ax3 = pr.ThirdAxisOfInertia();
        const Base::Vector3d v1(ax1.X(), ax1.Y(), ax1.Z());
        const Base::Vector3d v2(ax2.X(), ax2.Y(), ax2.Z());
        const Base::Vector3d v3(ax3.X(), ax3.Y(), ax3.Z());

        Base::Rotation rotation = plc.getRotation() * Base::Rotation::makeRotationByAxes(v1, v2, v3);
        data.pcs = Base::Placement(com, rotation);

        double ixx, iyy, izz;
        pr.Moments(ixx, iyy, izz);
        data.inertia = Base::Vector3d(ixx * density, iyy * density, izz * density);
        data.mass = gpr.Mass() * density;

        if (false) {
            if (pr.HasSymmetryPoint()) {
                std::cout << "  has symmetry point" << std::endl;
                // ok to return matrix of inertia
            }
            else if (pr.HasSymmetryAxis()) {
                std::cout << "  has symmetry axis" << std::endl;
                // 2 of three Ixx, Iyy, Izz are identical
            }
            else {
                std::cout << "  no symmetry axis" << std::endl;
            }

            std::cout << "  density: " << density << " " << std::endl;
            std::cout << "  mass: " << data.mass << std::endl;
            std::cout << "  inertias: " << data.inertia.x << " " << data.inertia.y << " "
                      << data.inertia.z << std::endl;
            std::cout << "  com: " << com.x << " " << com.y << " " << com.z << std::endl;

            // for (auto child in obj.ViewObject.claimChildrenRecursive()
        }
    }
    catch (const ::Part::AttachEngineException& e) {
        std::cerr << "Error computing inertial properties: " << e.what() << std::endl;
        Base::Vector3d com;
        const double l = 50.0;
        const double volume = l * l * l;  // assume 50mm cube
        data.mass = volume * density;
        const double ixx = data.mass * l * l / 6.0;  // inertia of cube around center
        shape.getCenterOfGravity(com);
        data.pcs = Base::Placement(com, Base::Rotation());
        data.inertia = Base::Vector3d(ixx, ixx, ixx);
    }
    return data;
}

AssemblyObject::MbDPartData AssemblyObject::getMbDData(App::DocumentObject* part)
{
    auto it = objectPartMap.find(part);
    std::string str = part->getFullName();

    if (it != objectPartMap.end()) {
        // part has been associated with an ASMTPart before
        // std::cout << "update part: " << str << std::endl;
        Base::Placement plc = getPlacementFromProp(part, "Placement");
        const AssemblyObject::MbDInertialData inertial_data = getMbDInertial(part);
        updateMbdPart(it->second.part, plc, inertial_data);
        return it->second;
    }

    // part has not been associated with an ASMTPart before
    // std::cout << "new part " << str << std::endl;
    std::shared_ptr<ASMTPart> mbdPart = makeMbdPart(str);

    Base::Placement plc;
    const AssemblyObject::MbDInertialData inertial_data = getMbDInertial(part);
    updateMbdPart(mbdPart, plc, inertial_data);

    mbdAssembly->addPart(mbdPart);
    MbDPartData data = {mbdPart, plc};
    objectPartMap[part] = data;  // Store the association

    // Associate other objects connected with fixed joints
    if (bundleFixed) {
        auto addConnectedFixedParts = [&](App::DocumentObject* currentPart, auto& self) -> void {
            std::vector<App::DocumentObject*> joints = getJointsOfPart(currentPart);
            for (auto* joint : joints) {
                JointType jointType = getJointType(joint);
                if (jointType == JointType::Fixed) {
                    App::DocumentObject* part1 = getMovingPartFromRef(joint, "Reference1");
                    App::DocumentObject* part2 = getMovingPartFromRef(joint, "Reference2");
                    App::DocumentObject* partToAdd = currentPart == part1 ? part2 : part1;

                    if (objectPartMap.find(partToAdd) != objectPartMap.end()) {
                        // already added
                        continue;
                    }

                    Base::Placement plci = getPlacementFromProp(partToAdd, "Placement");
                    MbDPartData partData = {mbdPart, plc.inverse() * plci};
                    objectPartMap[partToAdd] = partData;  // Store the association

                    // Recursively call for partToAdd
                    self(partToAdd, self);
                }
            }
        };

        addConnectedFixedParts(part, addConnectedFixedParts);
    }
    return data;
}

std::shared_ptr<ASMTPart> AssemblyObject::getMbDPart(App::DocumentObject* part)
{
    if (!part) {
        return nullptr;
    }
    return getMbDData(part).part;
}

std::shared_ptr<ASMTPart> AssemblyObject::makeMbdPart(std::string& name)
{
    auto mbdPart = ASMTPart::With();
    mbdPart->setName(name);
    return mbdPart;
}

void AssemblyObject::updateMbdPart(
    std::shared_ptr<ASMTPart> mbdPart,
    Base::Placement plc,
    const AssemblyObject::MbDInertialData& data
)
{
    auto massMarker = ASMTPrincipalMassMarker::With();

    auto aAPcm = FullMatrix<double>::With(3, 3);
    auto T = data.pcs.toMatrix();
    for (size_t i = 0; i < 3; i++) {
        for (size_t j = 0; j < 3; j++) {
            aAPcm->at(i)->at(j) = T[i][j];
        }
    }
    auto com = data.pcs.getPosition();
    auto rPcmP = std::make_shared<FullColumn<double>>(ListD {com.x, com.y, com.z});

    constexpr double defaultNonGeomMass = 1.0e-12;
    constexpr double defaultNonGeomInertiaFactor = 1.0;
    const double nonGeomMass
        = getEnvDouble("FREECAD_ASSEMBLY_NON_GEOM_MASS").value_or(defaultNonGeomMass);
    const double nonGeomInertiaFactor = getEnvDouble("FREECAD_ASSEMBLY_NON_GEOM_INERTIA_FACTOR")
                                            .value_or(defaultNonGeomInertiaFactor);

    const auto fallbackPositive = [](double value, double fallback) {
        return (std::isfinite(value) && value > 0.0) ? value : fallback;
    };

    const double mbdMass = fallbackPositive(data.mass, nonGeomMass);
    const double fallbackInertia = std::abs(mbdMass * nonGeomInertiaFactor);
    const double mbdIxx = fallbackPositive(data.inertia.x, fallbackInertia);
    const double mbdIyy = fallbackPositive(data.inertia.y, fallbackInertia);
    const double mbdIzz = fallbackPositive(data.inertia.z, fallbackInertia);

    massMarker->setMass(mbdMass);
    massMarker->setDensity(1.0);
    massMarker->setMomentOfInertias(mbdIxx, mbdIyy, mbdIzz);
    massMarker->setPosition3D(rPcmP);
    massMarker->setRotationMatrix(aAPcm);
    mbdPart->setPrincipalMassMarker(massMarker);

    Base::Vector3d pos = plc.getPosition();
    mbdPart->setPosition3D(pos.x, pos.y, pos.z);

    // TODO : replace with quaternion to simplify
    Base::Rotation rot = plc.getRotation();
    Base::Matrix4D mat;
    rot.getValue(mat);
    Base::Vector3d r0 = mat.getRow(0);
    Base::Vector3d r1 = mat.getRow(1);
    Base::Vector3d r2 = mat.getRow(2);
    mbdPart->setRotationMatrix(r0.x, r0.y, r0.z, r1.x, r1.y, r1.z, r2.x, r2.y, r2.z);
}

std::shared_ptr<ASMTMarker> AssemblyObject::makeMbdMarker(std::string& name, Base::Placement& plc)
{
    auto mbdMarker = ASMTMarker::With();
    mbdMarker->setName(name);

    Base::Vector3d pos = plc.getPosition();
    mbdMarker->setPosition3D(pos.x, pos.y, pos.z);

    // TODO : replace with quaternion to simplify
    Base::Rotation rot = plc.getRotation();
    Base::Matrix4D mat;
    rot.getValue(mat);
    Base::Vector3d r0 = mat.getRow(0);
    Base::Vector3d r1 = mat.getRow(1);
    Base::Vector3d r2 = mat.getRow(2);
    mbdMarker->setRotationMatrix(r0.x, r0.y, r0.z, r1.x, r1.y, r1.z, r2.x, r2.y, r2.z);

    return mbdMarker;
}

std::vector<ObjRef> AssemblyObject::getDownstreamParts(
    App::DocumentObject* part,
    App::DocumentObject* joint
)
{
    if (!part) {
        return {};
    }

    // First we deactivate the joint
    bool state = false;
    if (joint) {
        state = getJointActivated(joint);
        setJointActivated(joint, false);
    }

    std::vector<App::DocumentObject*> joints = getJoints();

    std::vector<ObjRef> connectedParts = {{part, nullptr}};
    traverseAndMarkConnectedParts(part, connectedParts, joints);

    std::vector<ObjRef> downstreamParts;
    for (auto& parti : connectedParts) {
        if (!isPartConnected(parti.obj) && (parti.obj != part)) {
            downstreamParts.push_back(parti);
        }
    }

    if (joint) {
        setJointActivated(joint, state);
    }

    return downstreamParts;
}

App::DocumentObject* AssemblyObject::getUpstreamMovingPart(
    App::DocumentObject* part,
    App::DocumentObject*& joint,
    std::string& name,
    std::vector<App::DocumentObject*> excludeJoints
)
{
    if (!part || isPartGrounded(part)) {
        return nullptr;
    }

    excludeJoints.push_back(joint);

    joint = getJointOfPartConnectingToGround(part, name, excludeJoints);
    JointType jointType = getJointType(joint);
    if (jointType != JointType::Fixed) {
        return part;
    }

    part = getMovingPartFromRef(joint, name == "Reference1" ? "Reference2" : "Reference1");

    return getUpstreamMovingPart(part, joint, name);
}

double AssemblyObject::getObjMass(App::DocumentObject* obj)
{
    if (!obj) {
        return 0.0;
    }

    for (auto& pair : objMasses) {
        if (pair.first == obj) {
            return pair.second;
        }
    }
    return 1.0;
}

void AssemblyObject::setObjMasses(std::vector<std::pair<App::DocumentObject*, double>> objectMasses)
{
    objMasses = objectMasses;
}

std::vector<AssemblyLink*> AssemblyObject::getSubAssemblies()
{
    std::vector<AssemblyLink*> subAssemblies = {};

    App::Document* doc = getDocument();

    std::vector<DocumentObject*> assemblies = doc->getObjectsOfType(
        Assembly::AssemblyLink::getClassTypeId()
    );
    for (auto assembly : assemblies) {
        if (hasObject(assembly)) {
            subAssemblies.push_back(freecad_cast<AssemblyLink*>(assembly));
        }
    }

    return subAssemblies;
}

void AssemblyObject::ensureIdentityPlacements()
{
    std::vector<App::DocumentObject*> group = Group.getValues();
    for (auto* obj : group) {
        // When used in assembly, link groups must have identity placements.
        if (obj->isLinkGroup()) {
            auto* link = dynamic_cast<App::Link*>(obj);
            auto* pPlc = obj->getPlacementProperty();
            if (!pPlc || !link) {
                continue;
            }

            Base::Placement plc = pPlc->getValue();
            if (plc.isIdentity()) {
                continue;
            }

            pPlc->setValue(Base::Placement());
            obj->purgeTouched();

            // To keep the LinkElement positions, we apply plc to their placements
            std::vector<App::DocumentObject*> elts = link->ElementList.getValues();
            for (auto* elt : elts) {
                pPlc = elt->getPlacementProperty();
                pPlc->setValue(plc * pPlc->getValue());
                elt->purgeTouched();
            }
        }
    }
}

void AssemblyObject::syncGroundedJoints()
{
    if (App::GetApplication().isRestoring()) {
        return;
    }

    std::vector<App::DocumentObject*> groundedJoints = getGroundedJoints();
    std::map<App::DocumentObject*, App::DocumentObject*> groundedMap;
    for (auto gJoint : groundedJoints) {
        auto propObj = dynamic_cast<App::PropertyLink*>(gJoint->getPropertyByName("ObjectToGround"));
        if (propObj && propObj->getValue()) {
            groundedMap[propObj->getValue()] = gJoint;
        }
    }

    std::vector<App::DocumentObject*> allParts = getAssemblyComponents(this);

    for (auto part : allParts) {
        if (!part) {
            continue;
        }
        auto propPlc = part->getPlacementProperty();
        if (!propPlc) {
            continue;
        }

        bool isReadOnly = propPlc->isReadOnly();
        auto it = groundedMap.find(part);
        bool hasJoint = (it != groundedMap.end());

        // Create grounding joint if placement is locked but no joint exists
        if (isReadOnly && !hasJoint) {
            Base::PyGILStateLocker lock;
            try {
                std::string docName = getDocument()->getName();
                std::string asmName = getNameInDocument();
                std::string partName = part->getNameInDocument();
                std::string code = "import FreeCAD\n"
                                   "try:\n"
                                   "    import JointObject\n"
                                   "    import UtilsAssembly\n"
                                   "    doc = FreeCAD.getDocument('"
                    + docName
                    + "')\n"
                      "    asm = doc.getObject('"
                    + asmName
                    + "')\n"
                      "    part = doc.getObject('"
                    + partName
                    + "')\n"
                      "    jg = UtilsAssembly.getJointGroup(asm)\n"
                      "    if jg:\n"
                      "        j = jg.newObject('App::FeaturePython', 'GroundedJoint')\n"
                      "        JointObject.GroundedJoint(j, part)\n"
                      "        if hasattr(JointObject, 'ViewProviderGroundedJoint') and getattr(j, "
                      "'ViewObject', None):\n"
                      "            JointObject.ViewProviderGroundedJoint(j.ViewObject)\n"
                      "        j.recompute()\n"
                      "except Exception as e:\n"
                      "    FreeCAD.Console.PrintError(str(e) + '\\n')\n";
                Base::Interpreter().runString(code.c_str());
            }
            catch (...) {
            }
        }
        // Delete grounding joint if placement lock was lifted
        else if (!isReadOnly && hasJoint) {
            getDocument()->removeObject(it->second->getNameInDocument());
        }
    }
}

int AssemblyObject::numberOfComponents() const
{
    return getAssemblyComponents(this).size();
}

bool AssemblyObject::isEmpty() const
{
    return numberOfComponents() == 0;
}
