// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <FCConfig.h>

#include <App/Application.h>
#include <App/Document.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <App/PropertyStandard.h>
#include <App/PropertyUnits.h>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRep_Builder.hxx>
#include <Mod/Assembly/App/AssemblyLink.h>
#include <Mod/Assembly/App/AssemblyObject.h>
#include <Mod/Assembly/App/ForceGroup.h>
#include <Mod/Assembly/App/JointGroup.h>
#include <Mod/Part/App/PartFeature.h>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Face.hxx>
#include <src/App/InitApplication.h>

class AssemblyObjectTest: public ::testing::Test
{
protected:
    static void SetUpTestSuite()
    {
        tests::initApplication();
    }

    void SetUp() override
    {
        _docName = App::GetApplication().getUniqueDocumentName("test");
        _doc = App::GetApplication().newDocument(_docName.c_str(), "testUser");
        _assemblyObj = _doc->addObject<Assembly::AssemblyObject>();
        _jointGroupObj = _assemblyObj->addObject<Assembly::JointGroup>("jointGroupTest");
        _forceGroupObj = _assemblyObj->addObject<Assembly::ForceGroup>("forceGroupTest");
    }

    void TearDown() override
    {
        App::GetApplication().closeDocument(_docName.c_str());
    }

    Assembly::AssemblyObject* getObject()
    {
        return _assemblyObj;
    }

    App::Document* getDoc()
    {
        return _doc;
    }

private:
    // TODO: use shared_ptr or something else here?
    Assembly::AssemblyObject* _assemblyObj;
    Assembly::JointGroup* _jointGroupObj;
    Assembly::ForceGroup* _forceGroupObj;
    App::Document* _doc;
    std::string _docName;
};

TEST_F(AssemblyObjectTest, createAssemblyObject)  // NOLINT
{
    // Arrange

    // Act

    // Assert
}

// Tests for commit: Assembly: refactor AssemblyObject, AssemblyLink, add AssemblyUtils

TEST_F(AssemblyObjectTest, isPartConnectedReturnsFalseForNull)  // NOLINT
{
    // isPartConnected must handle a nullptr safely (null-guard added in refactor)
    EXPECT_FALSE(getObject()->isPartConnected(nullptr));
}

TEST_F(AssemblyObjectTest, isPartGroundedReturnsFalseForNull)  // NOLINT
{
    // isPartGrounded must handle a nullptr safely (null-guard added in refactor)
    EXPECT_FALSE(getObject()->isPartGrounded(nullptr));
}

TEST_F(AssemblyObjectTest, isPartConnectedReturnsFalseForUnattachedPart)  // NOLINT
{
    // A box added to the document but not to the assembly should not be connected
    auto* box = getDoc()->addObject("Part::Box", "Box");
    EXPECT_FALSE(getObject()->isPartConnected(box));
}

TEST_F(AssemblyObjectTest, isPartGroundedReturnsFalseForUnattachedPart)  // NOLINT
{
    auto* box = getDoc()->addObject("Part::Box", "Box");
    EXPECT_FALSE(getObject()->isPartGrounded(box));
}

TEST_F(AssemblyObjectTest, assemblyLinkCreatesForceGroupAccessor)  // NOLINT
{
    // AssemblyLink no longer exposes a raw "Forces" property.
    // It provides force access through ForceGroup/getForces().
    auto* link = getDoc()->addObject<Assembly::AssemblyLink>();
    ASSERT_NE(link, nullptr);

    auto* forceGroup = link->ensureForceGroup();
    ASSERT_NE(forceGroup, nullptr);
    EXPECT_TRUE(link->getForces().empty());
}

// Tests for commit: Assembly: add ForceGroup C++ infrastructure

TEST_F(AssemblyObjectTest, getForceGroupReturnsNonNull)  // NOLINT
{
    // ForceGroup was added to the assembly in SetUp; getForceGroup should find it
    EXPECT_NE(getObject()->getForceGroup(), nullptr);
}

TEST_F(AssemblyObjectTest, forceGroupGetForcesEmptyInitially)  // NOLINT
{
    auto* fg = getObject()->getForceGroup();
    ASSERT_NE(fg, nullptr);
    EXPECT_TRUE(fg->getForces().empty());
}

namespace
{

// What the FEM material card states, and the same number in the units the
// calculation works in.
constexpr const char* solidDensityText = "1e-9 t/mm^3";
constexpr double solidDensityTonPerMm3 = 1.0e-9;
// 1 g of plies per m^2 of skin, which is how an areal mass is stated; the
// property itself holds its value in the internal unit system, kg/mm^2.
constexpr double skinArealMassKgPerMm2 = 1.0e-9;
constexpr double skinArealMassTonPerMm2 = 1.0e-12;
constexpr double boxSize = 10.0;

TopoDS_Shape makeBox()
{
    return BRepPrimAPI_MakeBox(boxSize, boxSize, boxSize).Shape();
}

TopoDS_Face aFaceOf(const TopoDS_Shape& shape)
{
    for (TopExp_Explorer it(shape, TopAbs_FACE); it.More(); it.Next()) {
        return TopoDS::Face(it.Current());
    }
    return TopoDS_Face();
}

TopoDS_Shape compoundOf(const TopoDS_Shape& first, const TopoDS_Shape& second)
{
    TopoDS_Compound compound;
    BRep_Builder builder;
    builder.MakeCompound(compound);
    builder.Add(compound, first);
    builder.Add(compound, second);
    return compound;
}

/// A part carrying `shape`, with the density the FEM material collector reads.
Part::Feature* addWeighablePart(App::Document* doc, const TopoDS_Shape& shape)
{
    auto* part = static_cast<Part::Feature*>(doc->addObject("Part::Feature", "WeighablePart"));
    part->Shape.setValue(shape);
    auto* material = static_cast<App::PropertyMap*>(
        part->addDynamicProperty("App::PropertyMap", "Material")
    );
    material->setValue("Density", solidDensityText);
    return part;
}

/// State what the part's skins weigh per unit area, as the composite shell does.
void stateArealMass(App::DocumentObject* part, double arealMassKgPerMm2)
{
    auto* areal = static_cast<App::PropertyArealMass*>(
        part->addDynamicProperty("App::PropertyArealMass", "ArealWeight")
    );
    areal->setValue(arealMassKgPerMm2);
}

}  // namespace

TEST_F(AssemblyObjectTest, mixedSolidAndSkinCompoundWeighsBothDimensions)  // NOLINT
{
    // A solid with a composite skin on one of its faces, which is the compound
    // getInertialPropsOfShape refuses: it reads the type of the first piece and
    // demands every later piece be of that type too.
    const TopoDS_Shape box = makeBox();
    auto* part = addWeighablePart(getDoc(), compoundOf(box, aFaceOf(box)));
    stateArealMass(part, skinArealMassKgPerMm2);

    const auto data = getObject()->getMbDInertial(part);

    // The solid by its volume, the skin by its area: 1000 mm^3 at 1e-9 t/mm^3
    // plus 100 mm^2 at 1e-12 t/mm^2.
    const double expected = (boxSize * boxSize * boxSize) * solidDensityTonPerMm3
        + (boxSize * boxSize) * skinArealMassTonPerMm2;
    EXPECT_NEAR(data.mass, expected, 1e-15);
}

TEST_F(AssemblyObjectTest, skinIsWeighedByItsAreaNotByADensity)  // NOLINT
{
    // A bare skin with both a density and an areal mass stated: the density
    // says nothing about a surface, so only the areal mass may weigh it.
    auto* part = addWeighablePart(getDoc(), aFaceOf(makeBox()));
    stateArealMass(part, skinArealMassKgPerMm2);

    const auto data = getObject()->getMbDInertial(part);

    EXPECT_NEAR(data.mass, (boxSize * boxSize) * skinArealMassTonPerMm2, 1e-18);
}

TEST_F(AssemblyObjectTest, skinWithoutAStatedArealMassWeighsNothing)  // NOLINT
{
    // Nothing is invented for a skin: a part that states no areal mass is
    // reported as weighing nothing, rather than weighed on a guess.
    auto* part = addWeighablePart(getDoc(), aFaceOf(makeBox()));

    const auto data = getObject()->getMbDInertial(part);

    EXPECT_DOUBLE_EQ(data.mass, 0.0);
}
