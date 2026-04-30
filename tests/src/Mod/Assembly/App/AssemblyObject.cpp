// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <FCConfig.h>

#include <App/Application.h>
#include <App/Document.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <Mod/Assembly/App/AssemblyLink.h>
#include <Mod/Assembly/App/AssemblyObject.h>
#include <Mod/Assembly/App/ForceGroup.h>
#include <Mod/Assembly/App/JointGroup.h>
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
