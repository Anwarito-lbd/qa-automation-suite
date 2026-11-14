// Reference Unreal Engine 5 C++ Automation & Gauntlet Verification Spec
// Target: AegisPay Backend Health & Frame-Budget Smoke Gate

#include "Misc/AutomationTest.h"
#include "HttpModule.h"
#include "Interfaces/IHttpRequest.h"
#include "Interfaces/IHttpResponse.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(
    FAegisPayLedgerHealthTest,
    "AegisPay.Smoke.LedgerHealthEndpoint",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter
)

bool FAegisPayLedgerHealthTest::RunTest(const FString& Parameters)
{
    FHttpModule& Http = FHttpModule::Get();
    TSharedRef<IHttpRequest, ESPMode::ThreadSafe> Request = Http.CreateRequest();
    Request->SetURL(TEXT("http://127.0.0.1:8000/health"));
    Request->SetVerb(TEXT("GET"));

    bool bCompleted = false;
    int32 StatusCode = 0;

    Request->OnProcessRequestComplete().BindLambda(
        [&bCompleted, &StatusCode](FHttpRequestPtr Req, FHttpResponsePtr Resp, bool bWasSuccessful)
        {
            if (bWasSuccessful && Resp.IsValid())
            {
                StatusCode = Resp->GetResponseCode();
            }
            bCompleted = true;
        });

    TestTrue(TEXT("HTTP health request dispatched"), Request->ProcessRequest());
    ADD_LATENT_AUTOMATION_COMMAND(FWaitForConditionCommand([&bCompleted]() { return bCompleted; }));
    TestEqual(TEXT("SUT health check returns HTTP 200"), StatusCode, 200);
    return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS
