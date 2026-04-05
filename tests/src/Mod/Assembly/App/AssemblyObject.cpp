// SPDX-License-Identifier: LGPL-2.1-or-later

#include <gtest/gtest.h>

#include <FCConfig.h>

#include <App/Application.h>
#include <App/Document.h>
#include <App/Expression.h>
#include <App/ObjectIdentifier.h>
#include <Mod/Assembly/App/AssemblyLink.h>
#include <Mod/Assembly/App/AssemblyObject.h>
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

TEST_F(AssemblyObjectTest, assemblyLinkHasForcesProperty)  // NOLINT
{
    // AssemblyLink gained a Forces property in the refactor
    auto* link = getDoc()->addObject<Assembly::AssemblyLink>();
    ASSERT_NE(link, nullptr);
    EXPECT_NE(link->getPropertyByName("Forces"), nullptr);
}
